import os
import json
import mimetypes
from pathlib import Path

try:
    from google.cloud import storage
    from google.cloud.exceptions import GoogleCloudError
    _STORAGE_AVAILABLE = True
except ImportError:
    _STORAGE_AVAILABLE = False
    storage = None
    GoogleCloudError = Exception

try:
    from lib.firebase import API_KEY
except Exception:
    try:
        import sys
        _this_dir = os.path.dirname(__file__)
        _project_root = os.path.abspath(os.path.join(_this_dir, '..'))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from lib.firebase import API_KEY
    except Exception:
        API_KEY = None

_BUCKET_CACHE = None

def _get_storage_bucket():
    global _BUCKET_CACHE
    
    # Nếu đã có cache, return
    if _BUCKET_CACHE is not None:
        return _BUCKET_CACHE
    
    if not _STORAGE_AVAILABLE:
        raise RuntimeError("Google Cloud Storage library not available. Please install google-cloud-storage")
    
    # Lấy bucket name
    bucket_name = os.environ.get('FIREBASE_STORAGE_BUCKET', '').strip()
    if bucket_name.startswith('gs://'):
        bucket_name = bucket_name[5:]
    
    if not bucket_name:
        # Try to get from firebase-service.json if available
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            service_file = os.path.join(project_root, 'lib', 'firebase-service.json')
            if os.path.isfile(service_file):
                with open(service_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    bucket_name = data.get('storage_bucket', '').strip()
                    if bucket_name.startswith('gs://'):
                        bucket_name = bucket_name[5:]
                    if not bucket_name:
                        project_id = data.get('project_id', '')
                        if project_id:
                            bucket_name = f"{project_id}.appspot.com"
        except Exception:
            pass
    
    if not bucket_name:
        raise RuntimeError("Storage bucket not configured. Please set FIREBASE_STORAGE_BUCKET environment variable")
    
    # Tạo storage client với credentials
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        service_file = os.path.join(project_root, 'lib', 'firebase-service.json')
        
        if os.path.isfile(service_file):
            from google.oauth2 import service_account
            credentials_obj = service_account.Credentials.from_service_account_file(service_file)
            project_id = None
            try:
                with open(service_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    project_id = data.get('project_id', '')
            except Exception:
                pass
            client = storage.Client(credentials=credentials_obj, project=project_id)
        else:
            # Fallback: thử dùng default credentials
            client = storage.Client()
        
        # Tạo bucket và lưu vào cache
        _BUCKET_CACHE = client.bucket(bucket_name)
        return _BUCKET_CACHE
    except Exception as e:
        raise RuntimeError(f"Failed to initialize storage bucket '{bucket_name}': {e}")


def upload_file_to_firebase_storage(file_path: str, conversation_id: str, id_token: str) -> tuple[str, str]:

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not _STORAGE_AVAILABLE:
        raise RuntimeError("Google Cloud Storage library not available. Please install google-cloud-storage")
    
    # Lấy bucket
    bucket = _get_storage_bucket()
    
    # Lấy tên file
    file_name = Path(file_path).name
    # Sanitize file name
    file_name = _sanitize_filename(file_name)
    
    # Xác định content type
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        extension = Path(file_path).suffix.lower()
        content_type_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.zip': 'application/zip',
            '.mp3': 'audio/mpeg', 
            '.wav': 'audio/x-wav',
            '.mp4': 'video/mp4',
        }
        content_type = content_type_map.get(extension, 'application/octet-stream')
    
    # Kiểm tra file size
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError(f"File is empty: {file_path}")
    
    print(f"[Upload SDK] File: {file_name}, Size: {file_size} bytes, Content-Type: {content_type}")
    
    # Tạo blob path
    blob_path = f"chat_files/{conversation_id}/{file_name}"
    
    try:
        # Tạo blob
        blob = bucket.blob(blob_path)
        
        # Upload file sử dụng SDK - tự xử lý mọi thứ
        print(f"[Upload SDK] Đang upload: {file_name} ({content_type})...")
        blob.upload_from_filename(file_path, content_type=content_type)
        
        # Make public để lấy link tải trực tiếp
        blob.make_public()
        
        # Lấy public URL
        file_url = blob.public_url
        
        print(f"[Upload SDK] Thành công: {file_url}")
        return file_url, content_type
        
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to upload file to Firebase Storage: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during upload: {e}")


def _sanitize_filename(filename: str) -> str:
    # Loại bỏ các ký tự không hợp lệ
    invalid_chars = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*']
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename

