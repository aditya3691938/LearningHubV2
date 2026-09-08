import os
import zipfile
import xml.etree.ElementTree as ET
import tempfile
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from flask import current_app

def process_scorm_package(zip_file, scorm_id_str, upload_base_folder):
    """
    Extracts a SCORM zip file into a temporary folder, uploads all files to S3/B2 via StorageService,
    and parses imsmanifest.xml to locate the launch file (href).
    Returns (launch_href, error_message).
    """
    from app.services.storage_service import StorageService
    
    # Create a temporary directory to extract the ZIP
    temp_dir = tempfile.mkdtemp()
    scorm_folder = os.path.join(temp_dir, str(scorm_id_str))
    os.makedirs(scorm_folder, exist_ok=True)

    zip_path = os.path.join(scorm_folder, 'package.zip')
    zip_file.save(zip_path)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(scorm_folder)
    except Exception as e:
        return None, f"Failed to extract SCORM zip package: {e}"

    manifest_path = os.path.join(scorm_folder, 'imsmanifest.xml')
    launch_href = None

    if not os.path.exists(manifest_path):
        launch_href, err = _fallback_launch_file(scorm_folder)
        if not launch_href:
            return None, "Invalid SCORM package: imsmanifest.xml missing and no launch file found."
    else:
        try:
            tree = ET.parse(manifest_path)
            root = tree.getroot()
            for elem in root.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]
            resource = root.find('.//resource')
            if resource is not None and 'href' in resource.attrib:
                launch_href = resource.attrib['href']
            else:
                launch_href, err = _fallback_launch_file(scorm_folder)
        except Exception as e:
            return None, f"Error parsing SCORM imsmanifest.xml: {e}"

    if not launch_href:
        return None, "Could not identify launch HTML file in SCORM manifest."

    # Upload all extracted files to StorageService (B2/S3)
    files_to_upload = []
    for root_dir, dirs, files in os.walk(scorm_folder):
        for f in files:
            if f == 'package.zip':
                continue
            local_path = os.path.join(root_dir, f)
            rel_path = os.path.relpath(local_path, scorm_folder).replace('\\', '/')
            files_to_upload.append((local_path, rel_path))

    def upload_worker(file_info):
        local_path, rel_path = file_info
        folder = f"scorm/{scorm_id_str}"
        # We need to create a file-like object that Flask's save() / StorageService expects
        # We can just open the file and mock the content_type
        content_type, _ = mimetypes.guess_type(local_path)
        with open(local_path, 'rb') as f_obj:
            class MockFileObj:
                def __init__(self, f_obj, c_type):
                    self.f = f_obj
                    self.content_type = c_type
                def read(self, *args): return self.f.read(*args)
                def seek(self, *args): return self.f.seek(*args)
                def save(self, path):
                    with open(path, 'wb') as out:
                        out.write(self.f.read())
            
            mock_file = MockFileObj(f_obj, content_type or 'application/octet-stream')
            # upload_file takes (file_obj, filename, folder)
            # filename here is the relative path, so B2 key will be scorm/{scorm_id_str}/{rel_path}
            StorageService.upload_file(mock_file, rel_path, folder=folder)

    # Use ThreadPoolExecutor to upload files concurrently
    # This prevents the web request from timing out on large SCORM packages
    # For local storage provider, this will just copy files
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(upload_worker, files_to_upload)

    return launch_href, None


def _fallback_launch_file(scorm_folder):
    for root_dir, dirs, files in os.walk(scorm_folder):
        for f in files:
            if f.lower() in ['index.html', 'story.html', 'index_lms.html', 'launch.html']:
                rel_path = os.path.relpath(os.path.join(root_dir, f), scorm_folder)
                return rel_path.replace('\\', '/'), None
    return None, "No fallback launch file found."

