import json
import urllib.request
import urllib.error
import os
import sys

_this_dir = os.path.dirname(__file__)
_project_root = os.path.abspath(os.path.join(_this_dir, '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from lib.firebase import API_KEY 
except Exception:
    try:
        from lib.firebase import API_KEY  # fallback to root lib/firebase
    except Exception:
        API_KEY = ""


def firebase_sign_in(email: str, password: str) -> str | None:
    if not API_KEY:
        raise ValueError('Missing API key. Set it in Chat/lib/firebase.py or lib/firebase')
    
    try:
        url = f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}'
        payload = {
            'email': email,
            'password': password,
            'returnSecureToken': True,
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            obj = json.loads(body)
            return obj.get('idToken')
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode('utf-8', errors='replace')
            print('Auth HTTPError:', err)
        except Exception:
            pass
        return None
    except Exception as exc:
        print('Auth Error:', exc)
        return None
