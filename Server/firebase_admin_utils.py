import os
import json

try:
    from dotenv import load_dotenv, find_dotenv  # type: ignore
    _dotenv_path = find_dotenv()
    if _dotenv_path:
        load_dotenv(_dotenv_path)
except Exception:
    pass

try:
    import firebase_admin
    from firebase_admin import credentials, auth as fb_auth, db
    _FIREBASE_AVAILABLE = True
except Exception:
    _FIREBASE_AVAILABLE = False

_firebase_initialized = False


def init_firebase_if_needed() -> None:
    global _firebase_initialized
    if _firebase_initialized or not _FIREBASE_AVAILABLE:
        return
    try:
        try:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            default_sa_path = os.path.join(project_root, 'lib', 'firebase-service.json')
            if os.path.isfile(default_sa_path):
                project_id = ''
                try:
                    with open(default_sa_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        project_id = (data.get('project_id') or '').strip()
                except Exception:
                    project_id = ''
                cred = credentials.Certificate(default_sa_path)
                db_url = os.environ.get('FIREBASE_DATABASE_URL', '').strip()
                if project_id or db_url:
                    opts = {}
                    if project_id:
                        opts['projectId'] = project_id
                    if db_url:
                        opts['databaseURL'] = db_url
                    firebase_admin.initialize_app(cred, opts)
                else:
                    firebase_admin.initialize_app(cred)
                _firebase_initialized = True
                print('[Auth] Firebase initialized from Chat/lib/firebase-service.json')
                return
        except Exception as e:
            print(f"[Auth] Failed to init from Chat/lib/firebase-service.json: {e}")

        # Try JSON from environment variable
        firebase_service_account_key = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY', '').strip()
        if firebase_service_account_key:
            try:
                cred_data = json.loads(firebase_service_account_key)
                cred = credentials.Certificate(cred_data)
                project_id = cred_data.get('project_id', '')
                db_url = os.environ.get('FIREBASE_DATABASE_URL', '').strip()
                if project_id or db_url:
                    opts = {}
                    if project_id:
                        opts['projectId'] = project_id
                    if db_url:
                        opts['databaseURL'] = db_url
                    firebase_admin.initialize_app(cred, opts)
                else:
                    firebase_admin.initialize_app(cred)
                _firebase_initialized = True
                print('[Auth] Firebase initialized from environment variable')
                return
            except Exception as e:
                print(f"[Auth] Failed to parse FIREBASE_SERVICE_ACCOUNT_KEY: {e}")

        # Fallback to file path from env
        cred_path = os.environ.get('FIREBASE_CREDENTIALS', '').strip() or os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
        if cred_path and os.path.isfile(cred_path):
            project_id = ''
            try:
                with open(cred_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    project_id = (data.get('project_id') or '').strip()
            except Exception:
                project_id = ''
            cred = credentials.Certificate(cred_path)
            db_url = os.environ.get('FIREBASE_DATABASE_URL', '').strip()
            if project_id or db_url:
                opts = {}
                if project_id:
                    opts['projectId'] = project_id
                if db_url:
                    opts['databaseURL'] = db_url
                firebase_admin.initialize_app(cred, opts)
            else:
                firebase_admin.initialize_app(cred)
            _firebase_initialized = True
            print('[Auth] Firebase initialized from file')
            return

        # Default application credentials
        db_url = os.environ.get('FIREBASE_DATABASE_URL', '').strip()
        if db_url:
            firebase_admin.initialize_app(options={'databaseURL': db_url})
        else:
            firebase_admin.initialize_app()
        _firebase_initialized = True
        print('[Auth] Firebase initialized with default credentials')
    except Exception as exc:
        print(f"[Auth] Firebase init failed: {exc}")
        print('[Auth] Please set FIREBASE_SERVICE_ACCOUNT_KEY or GOOGLE_APPLICATION_CREDENTIALS')
        _firebase_initialized = False


def verify_id_token(id_token: str) -> tuple[bool, str, str, str, str]:
    if not _FIREBASE_AVAILABLE:
        return False, 'auth_unavailable'
    init_firebase_if_needed()
    if not _firebase_initialized:
        return False, 'auth_not_initialized'
    try:
        decoded = fb_auth.verify_id_token(id_token, check_revoked=True, clock_skew_seconds=60)
        email = decoded.get('email') or ''
        name = decoded.get('name') or ''
        uid = decoded.get('uid') or 'unknown'
        label = email or name or uid
        return True, label, uid, email, name
    except Exception as exc:
        reason = f'invalid_token: {exc}'
        print(f"[Auth] Token verify failed: {reason}")
        return False, reason, '', '', ''


def get_user_by_email(email: str) -> dict | None:
    if not _FIREBASE_AVAILABLE:
        return None
    init_firebase_if_needed()
    if not _firebase_initialized:
        return None
    try:
        user_record = fb_auth.get_user_by_email(email)
        return {
            'uid': user_record.uid or '',
            'email': email,
            'displayName': user_record.display_name or ''
        }
    except Exception:
        return None


def get_user_profile(uid: str) -> dict | None:
    try:
        init_firebase_if_needed()
        ref = db.reference(f'/users/{uid}')
        data = ref.get() or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault('uid', uid)
        return data
    except Exception:
        return None


def list_friends(uid: str) -> list[dict]:
    """Return list of friend profiles for uid based on /users/{uid}/friends."""
    results: list[dict] = []
    try:
        init_firebase_if_needed()
        fref = db.reference(f'/users/{uid}/friends')
        friends = fref.get()
        # Defensive logging to help debug mismatched RTDB shapes
        try:
            ftype = type(friends).__name__
            preview = None
            if isinstance(friends, dict):
                preview = list(friends.keys())[:10]
            else:
                preview = str(friends)[:200]
            print(f"[FRIEND] list_friends: uid={uid} raw_type={ftype} preview={preview}")
        except Exception:
            pass

        if friends is None:
            friends = {}

        # Support multiple storage shapes: dict {uid: true}, list [uid,...], or dict of dicts
        if isinstance(friends, dict):
            for friend_uid, linked in friends.items():
                # linked can be truthy (True) or a dict/timestamp. Treat truthy values as linked.
                if not linked:
                    continue
                # If stored as { uid: { ...profile... } } try to extract uid key
                if isinstance(linked, dict) and not linked is True:
                    # If the dict itself contains an 'uid' field, use it; otherwise assume key is uid
                    friend_id = linked.get('uid') or friend_uid
                else:
                    friend_id = friend_uid
                prof = get_user_profile(friend_id) or {'uid': friend_id}
                email = prof.get('email') or ''
                if not email:
                    try:
                        email = get_email_for_uid(friend_id)
                    except Exception:
                        email = ''
                results.append({
                    'uid': prof.get('uid') or friend_id,
                    'email': email,
                    'displayName': prof.get('displayName') or ''
                })
        elif isinstance(friends, list):
            for item in friends:
                if isinstance(item, str):
                    friend_id = item
                elif isinstance(item, dict):
                    friend_id = item.get('uid') or item.get('id') or ''
                    if not friend_id:
                        # try to pull a single key
                        keys = list(item.keys())
                        friend_id = keys[0] if keys else ''
                else:
                    continue
                if not friend_id:
                    continue
                prof = get_user_profile(friend_id) or {'uid': friend_id}
                email = prof.get('email') or ''
                if not email:
                    try:
                        email = get_email_for_uid(friend_id)
                    except Exception:
                        email = ''
                results.append({
                    'uid': prof.get('uid') or friend_id,
                    'email': email,
                    'displayName': prof.get('displayName') or ''
                })
        else:
            # unexpected shape: log and return empty
            try:
                print(f"[FRIEND] list_friends: unexpected data type for /users/{uid}/friends -> {type(friends)}")
            except Exception:
                pass
    except Exception:
        pass
    return results


def ensure_user_profile(uid: str, email: str, display_name: str | None = None) -> None:
    """Create basic user profile at /users/{uid} if missing."""
    try:
        init_firebase_if_needed()
        ref = db.reference(f'/users/{uid}')
        current = ref.get()
        if not isinstance(current, dict):
            current = {}
        # Only set minimal fields if absent
        updates = {}
        if not current.get('email') and email:
            updates['email'] = email
        if not current.get('displayName') and display_name:
            updates['displayName'] = display_name
        if updates:
            ref.update(updates)
    except Exception:
        pass


def get_email_for_uid(uid: str) -> str:
    """Best-effort resolve email for a uid using Admin Auth, fallback RTDB profile."""
    try:
        init_firebase_if_needed()
        user_record = fb_auth.get_user(uid)
        if user_record and getattr(user_record, 'email', None):
            return user_record.email or ''
    except Exception:
        pass
    prof = get_user_profile(uid) or {}
    return prof.get('email') or ''


