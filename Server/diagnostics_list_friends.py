import sys
from pprint import pprint

try:
    from Server.firebase_admin_utils import init_firebase_if_needed, db
except Exception:
    from firebase_admin_utils import init_firebase_if_needed, db


def run(uid: str):
    print(f"Diagnostics for uid={uid}")
    try:
        init_firebase_if_needed()
    except Exception as e:
        print("init_firebase_if_needed() raised:", e)

    try:
        path = f"/users/{uid}"
        u = db.reference(path).get()
        print('\n/full user node:')
        pprint(u)
    except Exception as e:
        print(f"Failed to read {path}: {e}")

    try:
        path2 = f"/users/{uid}/friends"
        f = db.reference(path2).get()
        print('\n/friends node:')
        pprint(f)
    except Exception as e:
        print(f"Failed to read {path2}: {e}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 Server/diagnostics_list_friends.py <uid>")
        sys.exit(1)
    run(sys.argv[1])
