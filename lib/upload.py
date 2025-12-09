import os
import sys
import json
import mimetypes
import re
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
    import firebase_admin
    from firebase_admin import firestore as admin_firestore
    _FIRESTORE_AVAILABLE = True
except ImportError:
    _FIRESTORE_AVAILABLE = False
    firebase_admin = None
    admin_firestore = None

try:
    from dotenv import load_dotenv, find_dotenv
    _dotenv_path = find_dotenv()
    if _dotenv_path:
        load_dotenv(_dotenv_path)
except Exception:
    pass

# Bucket name từ environment variable hoặc default
_BUCKET_NAME = os.environ.get('FIREBASE_STORAGE_BUCKET', '').strip()
# Loại bỏ prefix gs:// nếu có
if _BUCKET_NAME.startswith('gs://'):
    _BUCKET_NAME = _BUCKET_NAME[5:]
_bucket = None


def _get_bucket():
    """Khởi tạo và trả về bucket instance - sử dụng Firebase Admin SDK (đơn giản hơn)."""
    global _bucket, _BUCKET_NAME
    
    # Sử dụng Firebase Admin SDK
    if firebase_admin and _FIRESTORE_AVAILABLE:
        try:
            # Kiểm tra xem app đã init chưa để tránh lỗi init lại
            try:
                firebase_admin.get_app()
            except ValueError:
                # Firebase chưa được init, thử init từ firebase_admin_utils
                try:
                    server_path = os.path.join(os.path.dirname(__file__), '..', 'Server')
                    if server_path not in sys.path:
                        sys.path.insert(0, server_path)
                    from Server.firebase_admin_utils import init_firebase_if_needed
                    init_firebase_if_needed()
                except Exception:
                    # Nếu không thể import, thử init trực tiếp
                    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                    cred_path = os.path.join(project_root, 'lib', 'firebase-service.json')
                    if os.path.isfile(cred_path):
                        from firebase_admin import credentials
                        cred = credentials.Certificate(cred_path)
                        # Lấy bucket name từ file hoặc env
                        bucket_name = os.environ.get('FIREBASE_STORAGE_BUCKET', '').strip()
                        if bucket_name.startswith('gs://'):
                            bucket_name = bucket_name[5:]
                        if not bucket_name:
                            with open(cred_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                project_id = data.get('project_id', '')
                                if project_id:
                                    bucket_name = f"{project_id}.appspot.com"
                        firebase_admin.initialize_app(cred, {'storageBucket': bucket_name})
            
            # Sử dụng Firebase Admin Storage
            from firebase_admin import storage as admin_storage
            return admin_storage.bucket()
        except Exception as e:
            print(f"[Upload] Warning: Could not use Firebase Admin Storage: {e}, falling back to Google Cloud Storage SDK")
    
    if not _STORAGE_AVAILABLE:
        raise RuntimeError("Google Cloud Storage library not available. Please install google-cloud-storage")
    
    if _bucket is not None:
        return _bucket
    
    # Lấy bucket name và credentials từ env hoặc từ firebase-service.json
    service_account_path = None
    if not _BUCKET_NAME:
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            service_account_path = os.path.join(project_root, 'lib', 'firebase-service.json')
            if os.path.isfile(service_account_path):
                with open(service_account_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Ưu tiên sử dụng storage_bucket nếu có
                    _BUCKET_NAME = data.get('storage_bucket', '').strip()
                    # Loại bỏ prefix gs:// nếu có
                    if _BUCKET_NAME.startswith('gs://'):
                        _BUCKET_NAME = _BUCKET_NAME[5:]
                    if not _BUCKET_NAME:
                        # Fallback: tạo từ project_id
                        project_id = data.get('project_id', '')
                        if project_id:
                            _BUCKET_NAME = f"{project_id}.appspot.com"
        except Exception:
            pass
    
    if not _BUCKET_NAME:
        raise RuntimeError("Storage bucket not configured. Please set FIREBASE_STORAGE_BUCKET environment variable")
    
    try:
        # Sử dụng service account file
        if not service_account_path:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            service_account_path = os.path.join(project_root, 'lib', 'firebase-service.json')
        
        if os.path.isfile(service_account_path):
            from google.oauth2 import service_account
            credentials_obj = service_account.Credentials.from_service_account_file(service_account_path)
            project_id = None
            try:
                with open(service_account_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    project_id = data.get('project_id', '')
            except Exception:
                pass
            client = storage.Client(credentials=credentials_obj, project=project_id)
        else:
            # Fallback: thử dùng default credentials
            client = storage.Client()
        
        _bucket = client.bucket(_BUCKET_NAME)
        return _bucket
    except Exception as e:
        raise RuntimeError(f"Failed to initialize storage bucket '{_BUCKET_NAME}': {e}")


def _sanitize_filename(filename: str) -> str:

    sanitized = re.sub(r'[<>:"|?*\\]', '_', filename)
    # Loại bỏ các ký tự điều khiển
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
    # Giới hạn độ dài tên file
    if len(sanitized) > 255:
        name, ext = os.path.splitext(sanitized)
        sanitized = name[:255 - len(ext)] + ext
    return sanitized if sanitized else "file"


def upload_file(file_path: str, conversation_id: str) -> tuple[str, str]:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not conversation_id or not conversation_id.strip():
        raise ValueError("conversation_id cannot be empty")
    
    conversation_id = conversation_id.strip()
    
    # Lấy tên file, hỗ trợ cả Windows và Unix paths
    file_name = Path(file_path).name
    # Sanitize file name để tránh ký tự đặc biệt
    file_name = _sanitize_filename(file_name)
    
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        extension = Path(file_path).suffix.lower()
        content_type_map = {
            '.mp3': 'audio/mpeg', 
            '.wav': 'audio/x-wav',
            '.m4a': 'audio/mp4',
            '.jpg': 'image/jpeg', 
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.zip': 'application/zip',
            '.mp4': 'video/mp4',
        }
        content_type = content_type_map.get(extension, 'application/octet-stream')
    
    try:
        bucket = _get_bucket()
        
        # Tạo blob path
        blob_path = f"chat_files/{conversation_id}/{file_name}"
        blob = bucket.blob(blob_path)
        
        print(f"[Upload SDK] Đang upload: {file_name} ({content_type})...")
        
        # Upload file - SDK tự xử lý mọi thứ
        blob.upload_from_filename(file_path, content_type=content_type)
        
        # Đặt file là public
        blob.make_public()
        
        # Lấy public URL
        public_url = blob.public_url
        
        print(f"[Upload SDK] Thành công: {public_url}")
        return public_url, content_type
    
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to upload file to Google Cloud Storage: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during file upload: {e}")


def _get_firestore_client():
    if not _FIRESTORE_AVAILABLE:
        raise RuntimeError("Firestore library not available. Please install firebase-admin")
    
    try:
        # Đảm bảo Firebase Admin đã được khởi tạo
        try:
            firebase_admin.get_app()
        except ValueError:
            # Firebase chưa được khởi tạo, thử khởi tạo từ firebase_admin_utils
            try:
                # Thêm Server vào path nếu chưa có
                server_path = os.path.join(os.path.dirname(__file__), '..', 'Server')
                if server_path not in sys.path:
                    sys.path.insert(0, server_path)
                from Server.firebase_admin_utils import init_firebase_if_needed
                init_firebase_if_needed()
            except Exception:
                # Nếu không thể import, thử khởi tạo trực tiếp
                try:
                    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                    service_account_path = os.path.join(project_root, 'lib', 'firebase-service.json')
                    if os.path.isfile(service_account_path):
                        from firebase_admin import credentials
                        cred = credentials.Certificate(service_account_path)
                        firebase_admin.initialize_app(cred)
                except Exception as init_error:
                    raise RuntimeError(f"Firebase not initialized and failed to initialize: {init_error}")
        
        # Lấy Firestore client từ firebase_admin
        return admin_firestore.client()
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Firestore client: {e}")


def send_message_file(conversation_id: str, sender_id: str, file_path: str) -> str:
    """
    Gửi message kèm file vào Firestore.
    
    Upload file lên Google Cloud Storage và lưu thông tin message vào Firestore
    với cấu trúc: conversations/{conversation_id}/messages/{message_id}
    
    Args:
        conversation_id: ID của conversation
        sender_id: ID của người gửi (senderId)
        file_path: Đường dẫn đến file cần upload
    
    Returns:
        str: Public URL của file đã upload
    
    Raises:
        FileNotFoundError: Nếu file không tồn tại
        ValueError: Nếu conversation_id hoặc sender_id rỗng
        RuntimeError: Nếu không thể upload file hoặc lưu vào Firestore
    """
    # Validate parameters
    if not conversation_id or not conversation_id.strip():
        raise ValueError("conversation_id cannot be empty")
    
    if not sender_id or not sender_id.strip():
        raise ValueError("sender_id cannot be empty")
    
    conversation_id = conversation_id.strip()
    sender_id = sender_id.strip()
    
    # Lấy tên file gốc (để lưu trong Firestore)
    original_file_name = Path(file_path).name
    
    # Upload file lên Storage (sẽ tự động sanitize file name trong upload_file)
    file_url, content_type = upload_file(file_path, conversation_id)
    
    # Xác định fileType (phần đầu của content_type, ví dụ: "image" từ "image/png")
    file_type = content_type.split("/")[0] if "/" in content_type else "application"
    
    try:
        # Khởi tạo Firestore client
        db = _get_firestore_client()
        
        # Tạo reference đến message document
        message_ref = db.collection("conversations")\
            .document(conversation_id)\
            .collection("messages")\
            .document()
        
        # Lưu message vào Firestore
        message_ref.set({
            "senderId": sender_id,
            "fileURL": file_url,
            "fileType": file_type,  # "image", "audio", "video", "application"
            "fileName": original_file_name,  # Lưu tên file gốc
            "timestamp": admin_firestore.SERVER_TIMESTAMP
        })
        
        return file_url
    
    except RuntimeError:
        # Re-raise RuntimeError từ _get_firestore_client hoặc upload_file
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to save message to Firestore: {e}")

