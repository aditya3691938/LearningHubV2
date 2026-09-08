"""
PPTonPage — Flask blueprint for serving the viewer bundle and .pptx decks.

Rendering happens entirely in the browser, so this backend only has two jobs:

  1. serve ``pptx-viewer.js``
  2. serve ``.pptx`` files with the CORS headers a cross-origin page needs

Quick start
-----------
    from flask import Flask
    from pptonpage import pptonpage

    app = Flask(__name__)
    app.register_blueprint(
        pptonpage(decks_dir="/srv/decks", allowed_origins="*"),
        url_prefix="/pptonpage",
    )

Then, on any page (including one on a different domain)::

    <script src="https://your-host/pptonpage/pptx-viewer.js"></script>
    <pptx-viewer src="https://your-host/pptonpage/decks/quarterly.pptx"></pptx-viewer>

Endpoints
---------
    GET  /pptx-viewer.js        the drop-in bundle
    GET  /decks/<path:name>     a .pptx file, CORS-enabled, range-capable
    GET  /decks/                JSON listing of available decks
"""

from __future__ import annotations

import os
import mimetypes
from pathlib import Path
from typing import Iterable, Sequence

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
mimetypes.add_type(PPTX_MIME, ".pptx")

# The bundle ships next to this module by default: server/../dist/pptx-viewer.js
_DEFAULT_BUNDLE = Path(__file__).resolve().parent.parent / "dist" / "pptx-viewer.js"


def _normalise_origins(allowed_origins: str | Sequence[str]) -> list[str] | str:
    if isinstance(allowed_origins, str):
        return allowed_origins
    return list(allowed_origins)


def _resolve_origin(allowed: list[str] | str, request_origin: str | None) -> str | None:
    """Echo the caller's Origin when it is allowed, else fall back sensibly."""
    if allowed == "*":
        return "*"
    if isinstance(allowed, str):
        return allowed
    if request_origin and request_origin in allowed:
        return request_origin
    return allowed[0] if allowed else None


def pptonpage(
    decks_dir: str | os.PathLike[str],
    *,
    bundle_path: str | os.PathLike[str] | None = None,
    allowed_origins: str | Sequence[str] = "*",
    cache_seconds: int = 3600,
    bundle_cache_seconds: int = 86400,
    allow_listing: bool = True,
    name: str = "pptonpage",
) -> Blueprint:
    """Build a blueprint that serves the viewer and a directory of decks.

    Parameters
    ----------
    decks_dir:
        Directory holding ``.pptx`` files. Paths are resolved inside this
        directory only; traversal attempts return 404.
    bundle_path:
        Location of ``pptx-viewer.js``. Defaults to ``../dist/pptx-viewer.js``
        relative to this file.
    allowed_origins:
        ``"*"`` (default) or an explicit list of origins permitted to fetch
        decks cross-origin, e.g. ``["https://intranet.example.com"]``.
    cache_seconds:
        ``max-age`` for deck responses.
    bundle_cache_seconds:
        ``max-age`` for the JS bundle.
    allow_listing:
        Expose ``GET /decks/`` returning a JSON list of decks.
    """
    decks_root = Path(decks_dir).resolve()
    bundle = Path(bundle_path).resolve() if bundle_path else _DEFAULT_BUNDLE
    allowed = _normalise_origins(allowed_origins)

    bp = Blueprint(name, __name__)

    def _cors(resp: Response, *, credentials: bool = False) -> Response:
        origin = _resolve_origin(allowed, request.headers.get("Origin"))
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            # Caches must key on Origin whenever the value can vary.
            if origin != "*":
                resp.headers.setdefault("Vary", "Origin")
            if credentials and origin != "*":
                resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers.setdefault("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        resp.headers.setdefault("Access-Control-Allow-Headers", "Range, Content-Type")
        # Lets the browser read Content-Length/Range for progress reporting.
        resp.headers.setdefault(
            "Access-Control-Expose-Headers",
            "Content-Length, Content-Range, Accept-Ranges, ETag",
        )
        resp.headers.setdefault("Access-Control-Max-Age", "86400")
        return resp

    @bp.route("/pptx-viewer.js", methods=["GET", "HEAD", "OPTIONS"])
    def viewer_bundle() -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status=204))
        if not bundle.is_file():
            current_app.logger.error("PPTonPage bundle missing at %s", bundle)
            abort(500, description="pptx-viewer.js has not been built yet.")
        resp = send_file(
            bundle,
            mimetype="text/javascript",
            conditional=True,
            max_age=bundle_cache_seconds,
        )
        return _cors(resp)

    @bp.route("/decks/", methods=["GET", "HEAD", "OPTIONS"])
    def list_decks() -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status=204))
        if not allow_listing:
            abort(404)
        decks: Iterable[Path] = sorted(decks_root.glob("**/*.pptx"))
        payload = [
            {
                "name": p.relative_to(decks_root).as_posix(),
                "size": p.stat().st_size,
                "url": f"{request.script_root}{bp.url_prefix or ''}/decks/"
                       f"{p.relative_to(decks_root).as_posix()}",
            }
            for p in decks
            if p.is_file()
        ]
        return _cors(jsonify(decks=payload))

    @bp.route("/decks/<path:deck>", methods=["GET", "HEAD", "OPTIONS"])
    def deck(deck: str) -> Response:
        if request.method == "OPTIONS":
            return _cors(Response(status=204))

        # Resolve inside decks_root only — blocks ../ traversal and symlink escapes.
        try:
            target = (decks_root / deck).resolve()
            target.relative_to(decks_root)
        except (ValueError, OSError):
            abort(404)
        if not target.is_file() or target.suffix.lower() != ".pptx":
            abort(404)

        resp = send_file(
            target,
            mimetype=PPTX_MIME,
            conditional=True,          # enables ETag / Range / 304s
            max_age=cache_seconds,
            download_name=target.name,
        )
        resp.headers["Accept-Ranges"] = "bytes"
        # Inline: the browser fetches this with JS, it should never download.
        resp.headers["Content-Disposition"] = f'inline; filename="{target.name}"'
        return _cors(resp)

    return bp


# --------------------------------------------------------------------------- #
# Runnable example: python -m pptonpage  (or: python server/pptonpage.py)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from flask import Flask, send_from_directory

    here = Path(__file__).resolve().parent
    root = here.parent

    app = Flask(__name__)
    app.register_blueprint(
        pptonpage(decks_dir=root / "demo" / "decks"),
        url_prefix="/pptonpage",
    )

    @app.route("/")
    def index():
        return send_from_directory(root / "demo", "index.html")

    @app.route("/<path:asset>")
    def demo_asset(asset: str):
        return send_from_directory(root / "demo", asset)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
