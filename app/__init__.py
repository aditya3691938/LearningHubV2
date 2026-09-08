import os
from flask import Flask, session, g, request, current_app
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from app.config import Config
from app.models import db

csrf = CSRFProtect()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    config_class.init_app(app)
    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    # Configure SQLite pragmas for high-concurrency (WAL mode & synchronous NORMAL)
    with app.app_context():
        if 'sqlite' in app.config.get('SQLALCHEMY_DATABASE_URI', ''):
            from sqlalchemy import event
            @event.listens_for(db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()



    # Register Blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.courses import courses_bp
    from app.routes.classes import classes_bp
    from app.routes.learners import learners_bp
    from app.routes.attendance import attendance_bp
    from app.routes.feedback import feedback_bp
    from app.routes.certificates import certificates_bp
    from app.routes.reports import reports_bp
    from app.routes.learning_wall import learning_wall_bp
    from app.routes.super_admin import super_admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(courses_bp, url_prefix='/courses')
    app.register_blueprint(classes_bp, url_prefix='/classes')
    app.register_blueprint(learners_bp, url_prefix='/learners')
    app.register_blueprint(attendance_bp, url_prefix='/attendance')
    app.register_blueprint(feedback_bp, url_prefix='/feedback')
    app.register_blueprint(certificates_bp, url_prefix='/certificates')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(learning_wall_bp, url_prefix='/learning_wall')
    app.register_blueprint(super_admin_bp)

    # Custom Jinja template filters
    @app.template_filter('format_duration')
    def format_duration_filter(hours):
        if not hours or float(hours) <= 0:
            return "0 hrs"
        hours = round(float(hours), 2)
        total_mins = int(round(hours * 60))
        hrs = total_mins // 60
        mins = total_mins % 60
        
        if hrs > 0 and mins > 0:
            return f"{hrs} hr{'s' if hrs > 1 else ''} {mins} mins"
        elif hrs > 0:
            return f"{hrs} hr{'s' if hrs > 1 else ''}"
        else:
            return f"{mins} mins"

    @app.template_filter('from_json')
    def from_json_filter(json_str):
        import json
        if not json_str:
            return {}
        try:
            return json.loads(json_str)
        except Exception:
            return {}

    from app.utils.tagging import format_tags_filter
    app.template_filter('format_tags')(format_tags_filter)

    # Global context processors for templates
    @app.context_processor
    def inject_global_vars():
        from app.services.gdrive_service import parse_gdrive_url
        learner_id = session.get('learner_id')
        user_notifications = []
        unread_notif_count = 0
        learner_points = 0
        if learner_id:
            try:
                from app.models.notification import LearnerNotification
                from app.models.user import Learner
                user_notifications = LearnerNotification.query.filter_by(learner_id=learner_id).order_by(LearnerNotification.created_at.desc()).limit(8).all()
                unread_notif_count = LearnerNotification.query.filter_by(learner_id=learner_id, is_read=False).count()
                
                learner = Learner.query.get(learner_id)
                if learner:
                    learner_points = learner.points or 0
            except Exception:
                pass

        open_tickets_count = 0
        if session.get('admin_logged_in', False):
            try:
                from app.models.issue import LmsIssue
                open_tickets_count = LmsIssue.query.filter_by(status='Open').count()
            except Exception:
                pass

        # Resolve learner theme preference
        learner_theme = 'navy'
        if 'learner_theme' in session:
            learner_theme = session['learner_theme']
        elif learner_id:
            from app.models.user import Learner
            learner = Learner.query.get(learner_id)
            if learner and learner.theme:
                learner_theme = learner.theme
                session['learner_theme'] = learner_theme

        return {
            'admin_logged_in': session.get('admin_logged_in', False),
            'admin_username': session.get('admin_username', 'admin'),
            'learner_id': learner_id,
            'learner_global_id': session.get('learner_global_id', None),
            'learner_points': learner_points,
            'parse_gdrive_url': parse_gdrive_url,
            'user_notifications': user_notifications,
            'unread_notif_count': unread_notif_count,
            'safe_endpoint': request.endpoint or '',
            'enable_content_authoring': current_app.config.get('ENABLE_CONTENT_AUTHORING', False),
            'learner_theme': learner_theme,
            'open_tickets_count': open_tickets_count
        }

    # Custom error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        from flask import render_template
        return render_template('errors/500.html'), 500

    @app.errorhandler(413)
    def request_entity_too_large(e):
        from flask import flash, redirect, request
        flash("The uploaded file is too large. Maximum allowed file size is 1 GB.", "danger")
        return redirect(request.referrer or '/')

    # Auto-initialize database tables and seed files on startup (Render/Waitress support)
    from app.seed import init_db_and_seed
    init_db_and_seed(app)

    return app
