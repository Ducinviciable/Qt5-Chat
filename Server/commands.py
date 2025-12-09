import json

try:
    from Server.firebase_admin_utils import get_user_by_email, list_friends, get_email_for_uid, ensure_user_profile
    from Server.firebase_admin_utils import init_firebase_if_needed
    from Server.firebase_admin_utils import db
    from Server.state import socket_to_user
    from Server.state import uid_to_socket
    from Server.state import file_chunks_storage, file_chunks_lock
    from Server.state import active_calls, active_calls_lock
except Exception:
    from firebase_admin_utils import get_user_by_email, list_friends, get_email_for_uid, ensure_user_profile
    from firebase_admin_utils import init_firebase_if_needed
    from firebase_admin_utils import db
    from state import socket_to_user
    from state import uid_to_socket
    from state import file_chunks_storage, file_chunks_lock
    from state import active_calls, active_calls_lock

# Handle type of command
def handle_command_line(conn, obj: dict):
    cmd_type = (obj.get('type') or '').upper()
    try:
        print(f"[CMD] received type={cmd_type} obj_keys={list(obj.keys())}")
    except Exception:
        pass
    if cmd_type == 'FIND_USER':
        _cmd_find_user(conn, obj)
    elif cmd_type == 'LIST_FRIENDS':
        _cmd_list_friends(conn)
    elif cmd_type == 'SEND_FRIEND_REQUEST':
        _cmd_send_friend_request(conn, obj)
    elif cmd_type == 'ACCEPT_REQUEST':
        _cmd_accept_request(conn, obj)
    elif cmd_type == 'REJECT_REQUEST':
        _cmd_reject_request(conn, obj)
    elif cmd_type == 'FRIEND_REQUESTS':
        _cmd_friend_requests(conn)
    elif cmd_type == 'SEND_DM':
        _cmd_send_dm(conn, obj)
    elif cmd_type == 'LOAD_THREAD':
        _cmd_load_thread(conn, obj)
    elif cmd_type == 'CREATE_GROUP':
        _cmd_create_group(conn, obj)
    elif cmd_type == 'LIST_GROUPS':
        _cmd_list_groups(conn)
    elif cmd_type == 'SEND_GROUP_MESSAGE':
        _cmd_send_group_message(conn, obj)
    elif cmd_type == 'LOAD_GROUP_HISTORY':
        _cmd_load_group_history(conn, obj)
    elif cmd_type == 'LEAVE_GROUP':
        _cmd_leave_group(conn, obj)
    elif cmd_type == 'LIST_GROUP_MEMBERS':
        _cmd_list_group_members(conn, obj)
    elif cmd_type == 'SEND_FILE':
        _cmd_send_file(conn, obj)
    elif cmd_type == 'SEND_FILE_URL':
        _cmd_send_file_url(conn, obj)
    elif cmd_type == 'SEND_FILE_START':
        _cmd_send_file_start(conn, obj)
    elif cmd_type == 'SEND_FILE_CHUNK':
        _cmd_send_file_chunk(conn, obj)
    elif cmd_type == 'SEND_FILE_END':
        _cmd_send_file_end(conn, obj)
    elif cmd_type == 'CALL_INVITE':
        _cmd_call_invite(conn, obj)
    elif cmd_type == 'CALL_ACCEPT':
        _cmd_call_accept(conn, obj)
    elif cmd_type == 'CALL_REJECT':
        _cmd_call_reject(conn, obj)
    elif cmd_type == 'CALL_END':
        _cmd_call_end(conn, obj)
    else:
        _send_cmd(conn, { 'type': 'ERROR', 'message': 'unknown_command' })


def _cmd_find_user(conn, obj: dict):
    email = (obj.get('email') or '').strip()
    if not email:
        _send_cmd(conn, { 'type': 'FIND_USER_RESULT', 'found': False, 'error': 'missing_email' })
        return
    record = get_user_by_email(email)
    if not record:
        _send_cmd(conn, { 'type': 'FIND_USER_RESULT', 'found': False, 'error': 'not_found' })
        return
    _send_cmd(conn, {
        'type': 'FIND_USER_RESULT',
        'found': True,
        'email': record.get('email') or email,
        'displayName': record.get('displayName') or '',
        'uid': record.get('uid') or ''
    })

# Send command to client
def _send_cmd(conn, obj: dict):
    try:
        conn.sendall(("CMD " + json.dumps(obj) + "\n").encode('utf-8'))
    except Exception:
        pass


def _cmd_list_friends(conn):
    # Pull uid from connection attribute set during AUTH
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        # Fallback resolve from socket_to_uid map
        try:
            from state import socket_to_uid as _s2u  # type: ignore
        except Exception:
            from state import socket_to_uid as _s2u  # type: ignore
        try:
            uid = _s2u.get(conn, '')
        except Exception:
            uid = ''
        if not uid:
            _send_cmd(conn, { 'type': 'FRIENDS', 'friends': [], 'error': 'unauthorized' })
            return
    friends = list_friends(uid)
    try:
        print(f"[FRIEND] LIST_FRIENDS uid={uid}: {len(friends)} item(s)")
    except Exception:
        pass
    _send_cmd(conn, { 'type': 'FRIENDS', 'friends': friends })


def _resolve_uid_from_obj(obj: dict) -> str:
    to_uid = (obj.get('toUid') or '').strip()
    if to_uid:
        return to_uid
    to_email = (obj.get('toEmail') or '').strip()
    if to_email:
        record = get_user_by_email(to_email)
        return (record or {}).get('uid') or ''
    return ''


def _make_thread_id(uid_a: str, uid_b: str) -> str:
    if uid_a <= uid_b:
        return f"{uid_a}__{uid_b}"
    return f"{uid_b}__{uid_a}"


def _cmd_send_dm(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        # try fallback
        try:
            from Server.state import socket_to_uid as _s2u  
        except Exception:
            from state import socket_to_uid as _s2u  
        uid = _s2u.get(conn, '') if _s2u else ''
    to_uid = (obj.get('toUid') or '').strip()
    text = (obj.get('text') or '').strip()
    client_msg_id = (obj.get('clientMsgId') or '').strip()
    if not uid or not to_uid or not text:
        _send_cmd(conn, { 'type': 'DM_DELIVERED', 'ok': False, 'clientMsgId': client_msg_id, 'error': 'missing_params' })
        return
    try:
        init_firebase_if_needed()
        thread_id = _make_thread_id(uid, to_uid)
        # Write message to database
        msg_ref = db.reference(f'/chats/{thread_id}/messages').push({
            'senderUid': uid,
            'text': text,
            'ts': {'.sv': 'timestamp'},
        })
        # Deliver to recipient if user online
        try:
            peer_socket = uid_to_socket.get(to_uid)
            if peer_socket is not None:
                _send_cmd(peer_socket, { 'type': 'DM', 'fromUid': uid, 'text': text, 'threadId': thread_id })
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'DM_DELIVERED', 'ok': True, 'clientMsgId': client_msg_id, 'threadId': thread_id })
    except Exception as e:
        _send_cmd(conn, { 'type': 'DM_DELIVERED', 'ok': False, 'clientMsgId': client_msg_id, 'error': f'{e}' })


def _cmd_load_thread(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Chat.Server.state import socket_to_uid as _s2u  # type: ignore
        except Exception:
            from state import socket_to_uid as _s2u  # type: ignore
        uid = _s2u.get(conn, '') if _s2u else ''
    peer_uid = (obj.get('peerUid') or '').strip()
    limit = obj.get('limit')
    if not uid or not peer_uid:
        _send_cmd(conn, { 'type': 'DM_HISTORY', 'ok': False, 'error': 'missing_params' })
        return
    try:
        init_firebase_if_needed()
        thread_id = _make_thread_id(uid, peer_uid)
        ref = db.reference(f'/chats/{thread_id}/messages')
        data = ref.get() or {}
        messages = []
        if isinstance(data, dict):
            for mid, m in data.items():
                if not isinstance(m, dict):
                    continue
                messages.append({
                    'id': mid,
                    'senderUid': m.get('senderUid') or '',
                    'text': m.get('text') or '',
                    'ts': m.get('ts') or 0,
                })
        # Sort by ts asc
        messages.sort(key=lambda x: x.get('ts') or 0)
        if isinstance(limit, int) and limit > 0:
            messages = messages[-limit:]
        
        # Load file messages từ Firestore
        try:
            from firebase_admin import firestore as admin_firestore
            db_fs = admin_firestore.client()
            fs_messages_ref = db_fs.collection("conversations").document(thread_id).collection("messages")
            fs_messages = fs_messages_ref.order_by("timestamp").limit(limit if isinstance(limit, int) and limit > 0 else 100).stream()
            
            for doc in fs_messages:
                msg_data = doc.to_dict()
                if msg_data:
                    # Convert Firestore timestamp to milliseconds
                    timestamp = msg_data.get('timestamp')
                    if hasattr(timestamp, 'timestamp'):
                        ts_ms = int(timestamp.timestamp() * 1000)
                    else:
                        ts_ms = 0
                    
                    messages.append({
                        'id': doc.id,
                        'senderUid': msg_data.get('senderId', ''),
                        'text': '',  # File message không có text
                        'ts': ts_ms,
                        'fileURL': msg_data.get('fileURL', ''),
                        'fileType': msg_data.get('fileType', 'application'),
                        'fileName': msg_data.get('fileName', 'Unknown')
                    })
        except Exception as e:
            print(f"[DM_HISTORY] Error loading Firestore messages: {e}")
        
        # Sort lại tất cả messages theo timestamp
        messages.sort(key=lambda x: x.get('ts') or 0)
        if isinstance(limit, int) and limit > 0:
            messages = messages[-limit:]
        
        _send_cmd(conn, { 'type': 'DM_HISTORY', 'ok': True, 'threadId': thread_id, 'peerUid': peer_uid, 'meUid': uid, 'messages': messages })
    except Exception as e:
        _send_cmd(conn, { 'type': 'DM_HISTORY', 'ok': False, 'error': f'{e}' })


def _cmd_send_friend_request(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        # Fallback resolve uid by the label (email) stored at handshake
        try:
            label = socket_to_user.get(conn) or ''
            if label:
                rec = get_user_by_email(label)
                if rec and rec.get('uid'):
                    uid = rec['uid']
                    try:
                        conn._chat_uid = uid  
                    except Exception:
                        pass
        except Exception:
            pass
    if not uid:
        try:
            print(f"[FRIEND] SEND_FRIEND_REQUEST unauthorized: conn has no uid. obj={obj}")
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_SENT', 'ok': False, 'error': 'unauthorized' })
        return
    to_uid = _resolve_uid_from_obj(obj)
    if not to_uid or to_uid == uid:
        try:
            print(f"[FRIEND] SEND_FRIEND_REQUEST invalid_target: from={uid}, to_uid={to_uid}, obj={obj}")
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_SENT', 'ok': False, 'error': 'invalid_target' })
        return
    try:
        init_firebase_if_needed()
        try:
            print(f"[FRIEND] SEND_FRIEND_REQUEST from={uid} to={to_uid}")
        except Exception:
            pass
        # Guard 1: already friends (either direction)
        already_a = bool(db.reference(f'/users/{uid}/friends/{to_uid}').get())
        already_b = bool(db.reference(f'/users/{to_uid}/friends/{uid}').get())
        if already_a or already_b:
            _send_cmd(conn, { 'type': 'FRIEND_REQUEST_SENT', 'ok': False, 'error': 'already_friends' })
            return

        # Guard 2: already has pending request
        req_ref = db.reference(f'/users/{to_uid}/incoming_requests/{uid}')
        if bool(req_ref.get()):
            _send_cmd(conn, { 'type': 'FRIEND_REQUEST_SENT', 'ok': False, 'error': 'already_requested' })
            return

        # Create request
        req_ref = db.reference(f'/users/{to_uid}/incoming_requests/{uid}')
        req_ref.set({ 'createdAt': {'.sv': 'timestamp'} })
        key = uid
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_SENT', 'ok': True, 'toUid': to_uid, 'requestId': key })
    except Exception as e:
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_SENT', 'ok': False, 'error': f'{e}' })


def _cmd_accept_request(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '') 
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u  
        except Exception:
            from state import socket_to_uid as _s2u  
        try:
            uid = _s2u.get(conn, '')
        except Exception:
            uid = ''
    from_uid = (obj.get('fromUid') or '').strip()
    if not from_uid:
        from_email = (obj.get('fromEmail') or '').strip()
        if from_email:
            rec = get_user_by_email(from_email)
            from_uid = (rec or {}).get('uid') or ''
    request_id = (obj.get('requestId') or '').strip()
    if not uid or not from_uid:
        try:
            print(f"[FRIEND] ACCEPT_REQUEST missing_params: uid={uid}, from_uid={from_uid}, obj={obj}")
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_ACCEPTED', 'ok': False, 'error': 'missing_params' })
        return
    try:
        init_firebase_if_needed()
        try:
            print(f"[FRIEND] ACCEPT_REQUEST uid={uid} from_uid={from_uid} request_id={request_id}")
        except Exception:
            pass
        # Create friendships both directions under /users
        db.reference(f'/users/{uid}/friends/{from_uid}').set(True)
        db.reference(f'/users/{from_uid}/friends/{uid}').set(True)
        # Remove request
        db.reference(f'/users/{uid}/incoming_requests/{from_uid}').delete()
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_ACCEPTED', 'ok': True, 'fromUid': from_uid })
    except Exception as e:
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_ACCEPTED', 'ok': False, 'error': f'{e}' })


def _cmd_reject_request(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u  
        except Exception:
            from state import socket_to_uid as _s2u  
        try:
            uid = _s2u.get(conn, '')
        except Exception:
            uid = ''
    from_uid = (obj.get('fromUid') or '').strip()
    if not from_uid:
        from_email = (obj.get('fromEmail') or '').strip()
        if from_email:
            rec = get_user_by_email(from_email)
            from_uid = (rec or {}).get('uid') or ''
    request_id = (obj.get('requestId') or '').strip()
    if not uid or not from_uid:
        try:
            print(f"[FRIEND] REJECT_REQUEST missing_params: uid={uid}, from_uid={from_uid}, obj={obj}")
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_REJECTED', 'ok': False, 'error': 'missing_params' })
        return
    try:
        init_firebase_if_needed()
        try:
            print(f"[FRIEND] REJECT_REQUEST uid={uid} from_uid={from_uid} request_id={request_id}")
        except Exception:
            pass
        # Remove request under /users
        db.reference(f'/users/{uid}/incoming_requests/{from_uid}').delete()
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_REJECTED', 'ok': True, 'fromUid': from_uid })
    except Exception as e:
        _send_cmd(conn, { 'type': 'FRIEND_REQUEST_REJECTED', 'ok': False, 'error': f'{e}' })


def _cmd_friend_requests(conn):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        # Fallback: attempt to fetch uid from state map by socket
        try:
            from Chat.Server.state import socket_to_uid as _s2u  # type: ignore
        except Exception:
            from state import socket_to_uid as _s2u 
        try:
            uid = _s2u.get(conn, '')
        except Exception:
            uid = ''
        if not uid:
            try:
                print("[FRIEND] REQUESTS unauthorized: connection has no uid")
            except Exception:
                pass
            _send_cmd(conn, { 'type': 'FRIEND_REQUESTS', 'requests': [], 'error': 'unauthorized' })
            return
    try:
        init_firebase_if_needed()
        path = f'/users/{uid}/incoming_requests'
        data = db.reference(path).get() or {}
        requests = []
        if isinstance(data, dict):
            for from_uid, r in data.items():
                created_at = r.get('createdAt') if isinstance(r, dict) else None
                # Resolve email for display
                try:
                    email = get_email_for_uid(from_uid) or ''
                except Exception:
                    email = ''
                requests.append({ 'requestId': from_uid, 'fromUid': from_uid, 'fromEmail': email, 'createdAt': created_at })
        try:
            print(f"[FRIEND] REQUESTS for uid={uid} path={path}: {len(requests)} item(s)")
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'FRIEND_REQUESTS', 'requests': requests })
    except Exception as e:
        _send_cmd(conn, { 'type': 'FRIEND_REQUESTS', 'requests': [], 'error': f'{e}' })


# Group chat commands
def _cmd_create_group(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    if not uid:
        _send_cmd(conn, { 'type': 'GROUP_CREATED', 'ok': False, 'error': 'unauthorized' })
        return
    
    group_name = (obj.get('name') or '').strip()
    member_uids = obj.get('memberUids') or []
    
    if not group_name or not member_uids:
        _send_cmd(conn, { 'type': 'GROUP_CREATED', 'ok': False, 'error': 'missing_params' })
        return
    
    try:
        init_firebase_if_needed()
        
        # Create group ID
        import uuid
        group_id = str(uuid.uuid4())
        
        # Get member details
        members = []
        for member_uid in member_uids:
            try:
                member_email = get_email_for_uid(member_uid) or ''
                member_name = ''
                # Try to get display name from user profile
                try:
                    user_ref = db.reference(f'/users/{member_uid}')
                    user_data = user_ref.get()
                    if isinstance(user_data, dict):
                        member_name = user_data.get('displayName', '')
                except Exception:
                    pass
                
                members.append({
                    'uid': member_uid,
                    'email': member_email,
                    'displayName': member_name or member_email.split('@')[0] if member_email else 'Unknown'
                })
            except Exception:
                members.append({
                    'uid': member_uid,
                    'email': '',
                    'displayName': 'Unknown'
                })
        
        # Add creator to members
        creator_email = get_email_for_uid(uid) or ''
        creator_name = ''
        try:
            user_ref = db.reference(f'/users/{uid}')
            user_data = user_ref.get()
            if isinstance(user_data, dict):
                creator_name = user_data.get('displayName', '')
        except Exception:
            pass
        
        members.append({
            'uid': uid,
            'email': creator_email,
            'displayName': creator_name or creator_email.split('@')[0] if creator_email else 'Unknown'
        })
        
        # Create group in database
        group_data = {
            'id': group_id,
            'name': group_name,
            'createdBy': uid,
            'createdAt': {'.sv': 'timestamp'},
            'members': {member['uid']: True for member in members}
        }
        
        # Store group data
        db.reference(f'/groups/{group_id}').set(group_data)
        
        # Add group to each member's groups list
        for member in members:
            db.reference(f'/users/{member["uid"]}/groups/{group_id}').set(True)
        
        # Send success response
        _send_cmd(conn, {
            'type': 'GROUP_CREATED',
            'ok': True,
            'groupId': group_id,
            'name': group_name,
            'members': members
        })
        
        try:
            print(f"[GROUP] Created group {group_name} (id={group_id}) with {len(members)} members")
        except Exception:
            pass
            
    except Exception as e:
        _send_cmd(conn, { 'type': 'GROUP_CREATED', 'ok': False, 'error': f'{e}' })


def _cmd_list_groups(conn):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    if not uid:
        _send_cmd(conn, { 'type': 'GROUPS', 'groups': [], 'error': 'unauthorized' })
        return
    
    try:
        init_firebase_if_needed()
        
        # Get user's groups
        user_groups_ref = db.reference(f'/users/{uid}/groups')
        user_groups = user_groups_ref.get() or {}
        
        groups = []
        for group_id in user_groups.keys():
            try:
                # Get group data
                group_ref = db.reference(f'/groups/{group_id}')
                group_data = group_ref.get()
                
                if not isinstance(group_data, dict):
                    continue
                
                # Get member details
                members = []
                group_members = group_data.get('members', {})
                for member_uid in group_members.keys():
                    try:
                        member_email = get_email_for_uid(member_uid) or ''
                        member_name = ''
                        try:
                            user_ref = db.reference(f'/users/{member_uid}')
                            user_data = user_ref.get()
                            if isinstance(user_data, dict):
                                member_name = user_data.get('displayName', '')
                        except Exception:
                            pass
                        
                        members.append({
                            'uid': member_uid,
                            'email': member_email,
                            'displayName': member_name or member_email.split('@')[0] if member_email else 'Unknown'
                        })
                    except Exception:
                        members.append({
                            'uid': member_uid,
                            'email': '',
                            'displayName': 'Unknown'
                        })
                
                groups.append({
                    'groupId': group_id,
                    'name': group_data.get('name', 'Unknown Group'),
                    'createdBy': group_data.get('createdBy', ''),
                    'createdAt': group_data.get('createdAt', 0),
                    'members': members
                })
                
            except Exception:
                continue
        
        _send_cmd(conn, { 'type': 'GROUPS', 'groups': groups })
        
        try:
            print(f"[GROUP] LIST_GROUPS for uid={uid}: {len(groups)} groups")
        except Exception:
            pass
            
    except Exception as e:
        _send_cmd(conn, { 'type': 'GROUPS', 'groups': [], 'error': f'{e}' })


def _cmd_send_group_message(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    group_id = (obj.get('groupId') or '').strip()
    text = (obj.get('text') or '').strip()
    
    if not uid or not group_id or not text:
        _send_cmd(conn, { 'type': 'GROUP_MESSAGE_DELIVERED', 'ok': False, 'error': 'missing_params' })
        return
    
    try:
        init_firebase_if_needed()
        
        # Check if user is member of group
        user_in_group = bool(db.reference(f'/users/{uid}/groups/{group_id}').get())
        if not user_in_group:
            _send_cmd(conn, { 'type': 'GROUP_MESSAGE_DELIVERED', 'ok': False, 'error': 'not_member' })
            return
        
        # Store message in database
        msg_ref = db.reference(f'/groups/{group_id}/messages').push({
            'senderUid': uid,
            'text': text,
            'ts': {'.sv': 'timestamp'},
        })
        
        # Get group members and deliver to online members
        group_data = db.reference(f'/groups/{group_id}').get() or {}
        group_members = group_data.get('members', {})
        
        for member_uid in group_members.keys():
            if member_uid == uid:  # Skip sender
                continue
            try:
                member_socket = uid_to_socket.get(member_uid)
                if member_socket is not None:
                    _send_cmd(member_socket, {
                        'type': 'GROUP_MESSAGE',
                        'groupId': group_id,
                        'senderUid': uid,
                        'text': text
                    })
            except Exception:
                pass
        
        _send_cmd(conn, { 'type': 'GROUP_MESSAGE_DELIVERED', 'ok': True, 'groupId': group_id })
        
    except Exception as e:
        _send_cmd(conn, { 'type': 'GROUP_MESSAGE_DELIVERED', 'ok': False, 'error': f'{e}' })


def _cmd_load_group_history(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    group_id = (obj.get('groupId') or '').strip()
    limit = obj.get('limit', 50)
    
    if not uid or not group_id:
        _send_cmd(conn, { 'type': 'GROUP_HISTORY', 'ok': False, 'error': 'missing_params' })
        return
    
    try:
        init_firebase_if_needed()
        # Allow loading history even if user left the group (read-only view)
        
        # Get group messages
        messages_ref = db.reference(f'/groups/{group_id}/messages')
        data = messages_ref.get() or {}
        messages = []
        
        if isinstance(data, dict):
            for mid, m in data.items():
                if not isinstance(m, dict):
                    continue
                messages.append({
                    'id': mid,
                    'senderUid': m.get('senderUid') or '',
                    'text': m.get('text') or '',
                    'ts': m.get('ts') or 0,
                })
        
        # Sort by timestamp ascending
        messages.sort(key=lambda x: x.get('ts') or 0)
        
        # Load file messages từ Firestore
        try:
            from firebase_admin import firestore as admin_firestore
            db_fs = admin_firestore.client()
            fs_messages_ref = db_fs.collection("conversations").document(group_id).collection("messages")
            fs_messages = fs_messages_ref.order_by("timestamp").limit(limit if isinstance(limit, int) and limit > 0 else 100).stream()
            
            for doc in fs_messages:
                msg_data = doc.to_dict()
                if msg_data:
                    # Convert Firestore timestamp to milliseconds
                    timestamp = msg_data.get('timestamp')
                    if hasattr(timestamp, 'timestamp'):
                        ts_ms = int(timestamp.timestamp() * 1000)
                    else:
                        ts_ms = 0
                    
                    messages.append({
                        'id': doc.id,
                        'senderUid': msg_data.get('senderId', ''),
                        'text': '',  # File message không có text
                        'ts': ts_ms,
                        'fileURL': msg_data.get('fileURL', ''),
                        'fileType': msg_data.get('fileType', 'application'),
                        'fileName': msg_data.get('fileName', 'Unknown')
                    })
        except Exception as e:
            print(f"[GROUP_HISTORY] Error loading Firestore messages: {e}")
        
        # Sort lại tất cả messages theo timestamp
        messages.sort(key=lambda x: x.get('ts') or 0)
        
        # Apply limit
        if isinstance(limit, int) and limit > 0:
            messages = messages[-limit:]
        
        _send_cmd(conn, {
            'type': 'GROUP_HISTORY',
            'ok': True,
            'groupId': group_id,
            'meUid': uid,  # Thêm meUid để client biết tin nhắn nào là của mình
            'messages': messages
        })
        
    except Exception as e:
        _send_cmd(conn, { 'type': 'GROUP_HISTORY', 'ok': False, 'error': f'{e}' })


# --- Additional group commands: leave and list members ---
def _require_uid(conn) -> str:
    uid = getattr(conn, '_chat_uid', '')
    if uid:
        return uid
    try:
        from Chat.Server.state import socket_to_uid as _s2u  # type: ignore
    except Exception:
        from state import socket_to_uid as _s2u  # type: ignore
    try:
        return _s2u.get(conn, '')
    except Exception:
        return ''


def _cmd_leave_group(conn, obj: dict):
    uid = _require_uid(conn)
    group_id = (obj.get('groupId') or '').strip()
    if not uid or not group_id:
        _send_cmd(conn, { 'type': 'LEAVE_GROUP_OK', 'ok': False, 'error': 'missing_params' })
        return
    try:
        init_firebase_if_needed()
        # Remove from group members and user's group list
        db.reference(f'/groups/{group_id}/members/{uid}').delete()
        db.reference(f'/users/{uid}/groups/{group_id}').delete()
        # Compose system text and persist as a system message
        try:
            leaver_email = get_email_for_uid(uid) or ''
        except Exception:
            leaver_email = uid
        sys_text = f"{leaver_email} đã rời nhóm"
        try:
            db.reference(f'/groups/{group_id}/messages').push({
                'senderUid': '',
                'system': True,
                'text': sys_text,
                'ts': {'.sv': 'timestamp'},
            })
        except Exception:
            pass
        # Notify remaining online members in realtime
        try:
            mems = db.reference(f'/groups/{group_id}/members').get() or {}
            if isinstance(mems, dict):
                for m_uid, linked in mems.items():
                    if not linked:
                        continue
                    try:
                        peer_socket = uid_to_socket.get(m_uid)
                        if peer_socket is not None:
                            _send_cmd(peer_socket, { 'type': 'GROUP_SYSTEM', 'groupId': group_id, 'event': 'member_left', 'uid': uid, 'text': sys_text })
                    except Exception:
                        pass
        except Exception:
            pass
        _send_cmd(conn, { 'type': 'LEAVE_GROUP_OK', 'ok': True, 'groupId': group_id })
    except Exception as e:
        _send_cmd(conn, { 'type': 'LEAVE_GROUP_OK', 'ok': False, 'error': f'{e}' })


def _cmd_list_group_members(conn, obj: dict):
    uid = _require_uid(conn)
    group_id = (obj.get('groupId') or '').strip()
    if not uid or not group_id:
        _send_cmd(conn, { 'type': 'GROUP_MEMBERS', 'ok': False, 'members': [], 'error': 'missing_params' })
        return
    try:
        init_firebase_if_needed()
        # Require membership to view
        in_group = bool(db.reference(f'/users/{uid}/groups/{group_id}').get())
        if not in_group:
            _send_cmd(conn, { 'type': 'GROUP_MEMBERS', 'ok': False, 'members': [], 'error': 'not_member' })
            return
        mems = db.reference(f'/groups/{group_id}/members').get() or {}
        members: list[dict] = []
        if isinstance(mems, dict):
            for m_uid, linked in mems.items():
                if not linked:
                    continue
                try:
                    email = get_email_for_uid(m_uid) or ''
                except Exception:
                    email = ''
                members.append({ 'uid': m_uid, 'email': email })
        _send_cmd(conn, { 'type': 'GROUP_MEMBERS', 'ok': True, 'groupId': group_id, 'members': members })
    except Exception as e:
        _send_cmd(conn, { 'type': 'GROUP_MEMBERS', 'ok': False, 'members': [], 'error': f'{e}' })


def _cmd_send_file(conn, obj: dict):
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    if not uid:
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'error': 'unauthorized' })
        return
    
    # Lấy file content
    file_content_b64 = obj.get('fileContent', '').strip()
    file_name = obj.get('fileName', '').strip()
    file_path = obj.get('filePath', '').strip()
    to_uid = obj.get('toUid', '').strip()
    group_id = obj.get('groupId', '').strip()
    client_msg_id = obj.get('clientMsgId', '').strip()
    
    # Kiểm tra tham số
    if (not file_content_b64 and not file_path) or (not to_uid and not group_id):
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': 'missing_params' })
        return
    
    # Nếu có fileContent thì dùng fileContent, nếu không thì dùng filePath
    temp_file_path = None
    if file_content_b64:
        if not file_name:
            _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': 'missing_file_name' })
            return
    
    try:
        # Import upload functions
        import sys
        import os
        import base64
        import tempfile
        lib_path = os.path.join(os.path.dirname(__file__), '..', 'lib')
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from upload import send_message_file
        
        # Nếu có fileContent, decode và lưu vào temp file
        if file_content_b64:
            temp_file_path_local = None
            try:
                file_content = base64.b64decode(file_content_b64)
                # Tạo temp file
                temp_fd, temp_file_path_local = tempfile.mkstemp(suffix=os.path.splitext(file_name)[1] if file_name else '')
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    temp_file.write(file_content)
                # Dùng temp file path để upload
                file_path = temp_file_path_local
                temp_file_path = temp_file_path_local  # Set the outer scope variable
            except Exception as e:
                print(f"[FILE] Error decoding file content: {e}")
                # Clean up temp file nếu đã được tạo
                if temp_file_path_local and os.path.exists(temp_file_path_local):
                    try:
                        os.remove(temp_file_path_local)
                    except Exception:
                        pass
                _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': f'decode_error: {str(e)}' })
                return
        
        # Xác định conversation_id
        if group_id:
            # Nhóm: dùng group_id làm conversation_id
            conversation_id = group_id
            is_group = True
        else:
            # DM: tạo thread_id
            conversation_id = _make_thread_id(uid, to_uid)
            is_group = False
        
        # Upload file và lưu vào Firestore
        file_url = send_message_file(conversation_id, uid, file_path)
        
        # Clean up temp file nếu có
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
        
        # Lấy thông tin file từ Firestore để gửi về client
        try:
            from firebase_admin import firestore as admin_firestore
            db_fs = admin_firestore.client()
            messages_ref = db_fs.collection("conversations").document(conversation_id).collection("messages")
            # Lấy message mới nhất
            docs = messages_ref.order_by("timestamp", direction=admin_firestore.Query.DESCENDING).limit(1).stream()
            file_info = None
            for doc in docs:
                file_info = doc.to_dict()
                break
        except Exception:
            file_info = None
        
        file_type = file_info.get('fileType', 'application') if file_info else 'application'
        # Ưu tiên dùng fileName từ request, nếu không thì lấy từ Firestore, cuối cùng mới dùng basename của file_path
        file_name = file_name if file_name else (file_info.get('fileName', os.path.basename(file_path)) if file_info else os.path.basename(file_path))
        
        # Gửi notification cho người nhận nếu là DM
        if not is_group:
            try:
                peer_socket = uid_to_socket.get(to_uid)
                if peer_socket is not None:
                    _send_cmd(peer_socket, {
                        'type': 'FILE_MESSAGE',
                        'fromUid': uid,
                        'fileURL': file_url,
                        'fileType': file_type,
                        'fileName': file_name,
                        'threadId': conversation_id
                    })
            except Exception:
                pass
        
        # Gửi notification cho các member trong group
        elif is_group:
            try:
                init_firebase_if_needed()
                group_data = db.reference(f'/groups/{group_id}').get() or {}
                group_members = group_data.get('members', {})
                
                for member_uid in group_members.keys():
                    if member_uid == uid:  # Skip sender
                        continue
                    try:
                        member_socket = uid_to_socket.get(member_uid)
                        if member_socket is not None:
                            _send_cmd(member_socket, {
                                'type': 'FILE_MESSAGE',
                                'groupId': group_id,
                                'senderUid': uid,
                                'fileURL': file_url,
                                'fileType': file_type,
                                'fileName': file_name
                            })
                    except Exception:
                        pass
            except Exception:
                pass
        
        _send_cmd(conn, { 
            'type': 'FILE_SENT', 
            'ok': True, 
            'clientMsgId': client_msg_id, 
            'fileURL': file_url,
            'fileType': file_type,
            'fileName': file_name,
            'conversationId': conversation_id
        })
        
    except Exception as e:
        print(f"[FILE] SEND_FILE error: {e}")
        import traceback
        traceback.print_exc()
        # Clean up temp file nếu có
        if 'temp_file_path' in locals() and temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': str(e) })


def _cmd_send_file_url(conn, obj: dict):
    """
    Xử lý khi client gửi file URL (đã upload lên Firebase Storage).
    Chỉ cần lưu vào Firestore và forward URL cho client khác.
    """
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    if not uid:
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'error': 'unauthorized' })
        return
    
    file_url = obj.get('fileURL', '').strip()
    file_name = obj.get('fileName', '').strip()
    file_type = obj.get('fileType', 'application').strip()
    to_uid = obj.get('toUid', '').strip()
    group_id = obj.get('groupId', '').strip()
    client_msg_id = obj.get('clientMsgId', '').strip()
    
    if not file_url or not file_name or (not to_uid and not group_id):
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': 'missing_params' })
        return
    
    try:
        # Xác định conversation_id
        if group_id:
            conversation_id = group_id
            is_group = True
        else:
            conversation_id = _make_thread_id(uid, to_uid)
            is_group = False
        
        # Lưu message vào Firestore
        try:
            from firebase_admin import firestore as admin_firestore
            db_fs = admin_firestore.client()
            message_ref = db_fs.collection("conversations").document(conversation_id).collection("messages").document()
            message_ref.set({
                "senderId": uid,
                "fileURL": file_url,
                "fileType": file_type,
                "fileName": file_name,
                "timestamp": admin_firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"[FILE_URL] Error saving to Firestore: {e}")
            # Tiếp tục dù có lỗi Firestore, vẫn forward message
        
        # Gửi notification cho người nhận nếu là DM
        if not is_group:
            try:
                peer_socket = uid_to_socket.get(to_uid)
                if peer_socket is not None:
                    _send_cmd(peer_socket, {
                        'type': 'FILE_MESSAGE',
                        'fromUid': uid,
                        'fileURL': file_url,
                        'fileType': file_type,
                        'fileName': file_name,
                        'threadId': conversation_id
                    })
            except Exception:
                pass
        
        # Gửi notification cho các member trong group
        elif is_group:
            try:
                init_firebase_if_needed()
                group_data = db.reference(f'/groups/{group_id}').get() or {}
                group_members = group_data.get('members', {})
                
                for member_uid in group_members.keys():
                    if member_uid == uid:
                        continue
                    try:
                        member_socket = uid_to_socket.get(member_uid)
                        if member_socket is not None:
                            _send_cmd(member_socket, {
                                'type': 'FILE_MESSAGE',
                                'groupId': group_id,
                                'senderUid': uid,
                                'fileURL': file_url,
                                'fileType': file_type,
                                'fileName': file_name
                            })
                    except Exception:
                        pass
            except Exception:
                pass
        
        _send_cmd(conn, { 
            'type': 'FILE_SENT', 
            'ok': True, 
            'clientMsgId': client_msg_id, 
            'fileURL': file_url,
            'fileType': file_type,
            'fileName': file_name,
            'conversationId': conversation_id
        })
        
    except Exception as e:
        print(f"[FILE_URL] SEND_FILE_URL error: {e}")
        import traceback
        traceback.print_exc()
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': str(e) })


def _cmd_send_file_start(conn, obj: dict):
    """Nhận metadata của file chunking"""
    uid = getattr(conn, '_chat_uid', '')
    if not uid:
        try:
            from Server.state import socket_to_uid as _s2u
        except Exception:
            from state import socket_to_uid as _s2u
        uid = _s2u.get(conn, '') if _s2u else ''
    
    if not uid:
        _send_cmd(conn, { 'type': 'FILE_CHUNK_ERROR', 'error': 'unauthorized' })
        return
    
    client_msg_id = obj.get('clientMsgId', '').strip()
    file_name = obj.get('fileName', '').strip()
    file_size = obj.get('fileSize', 0)
    to_uid = obj.get('toUid', '').strip()
    group_id = obj.get('groupId', '').strip()
    
    if not client_msg_id or not file_name or file_size <= 0 or (not to_uid and not group_id):
        _send_cmd(conn, { 'type': 'FILE_CHUNK_ERROR', 'error': 'missing_params' })
        return
    
    # Khởi tạo storage cho chunks
    with file_chunks_lock:
        file_chunks_storage[client_msg_id] = {
            'chunks': {},  # {chunk_index: chunk_data_b64}
            'file_name': file_name,
            'file_size': file_size,
            'to_uid': to_uid,
            'group_id': group_id,
            'conn': conn,
            'uid': uid
        }
    
    _send_cmd(conn, { 'type': 'FILE_CHUNK_STARTED', 'clientMsgId': client_msg_id })


def _cmd_send_file_chunk(conn, obj: dict):
    """Nhận một chunk của file"""
    client_msg_id = obj.get('clientMsgId', '').strip()
    chunk_index = obj.get('chunkIndex', -1)
    chunk_data_b64 = obj.get('chunkData', '').strip()
    
    if not client_msg_id or chunk_index < 0 or not chunk_data_b64:
        _send_cmd(conn, { 'type': 'FILE_CHUNK_ERROR', 'error': 'missing_params' })
        return
    
    # Lưu chunk vào storage
    with file_chunks_lock:
        if client_msg_id not in file_chunks_storage:
            _send_cmd(conn, { 'type': 'FILE_CHUNK_ERROR', 'error': 'no_start_command' })
            return
        
        storage = file_chunks_storage[client_msg_id]
        storage['chunks'][chunk_index] = chunk_data_b64
    
    _send_cmd(conn, { 'type': 'FILE_CHUNK_RECEIVED', 'chunkIndex': chunk_index, 'clientMsgId': client_msg_id })


def _cmd_send_file_end(conn, obj: dict):
    """Kết thúc nhận chunks, ghép lại và upload"""
    client_msg_id = obj.get('clientMsgId', '').strip()
    
    if not client_msg_id:
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'error': 'missing_client_msg_id' })
        return
    
    # Lấy storage
    with file_chunks_lock:
        if client_msg_id not in file_chunks_storage:
            _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': 'no_chunks_received' })
            return
        
        storage = file_chunks_storage.pop(client_msg_id)
    
    chunks = storage['chunks']
    if not chunks:
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': 'no_chunks' })
        return
    
    try:
        import base64
        sorted_indices = sorted(chunks.keys())
        file_content_parts = []
        for i in sorted_indices:
            chunk_b64 = chunks[i]
            chunk_data = base64.b64decode(chunk_b64)
            file_content_parts.append(chunk_data)
        
        # Ghép lại tất cả các chunks
        file_content = b''.join(file_content_parts)
        
        # Lưu vào temp file
        import tempfile
        import os
        temp_fd, temp_file_path = tempfile.mkstemp(suffix=os.path.splitext(storage['file_name'])[1] if storage['file_name'] else '')
        with os.fdopen(temp_fd, 'wb') as temp_file:
            temp_file.write(file_content)
        
        # Import upload functions
        import sys
        lib_path = os.path.join(os.path.dirname(__file__), '..', 'lib')
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from upload import send_message_file
        
        # Xác định conversation_id
        if storage['group_id']:
            conversation_id = storage['group_id']
            is_group = True
        else:
            conversation_id = _make_thread_id(storage['uid'], storage['to_uid'])
            is_group = False
        
        # Upload file
        file_url = send_message_file(conversation_id, storage['uid'], temp_file_path)
        
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
        
        # Lấy thông tin file từ Firestore
        try:
            from firebase_admin import firestore as admin_firestore
            db_fs = admin_firestore.client()
            messages_ref = db_fs.collection("conversations").document(conversation_id).collection("messages")
            docs = messages_ref.order_by("timestamp", direction=admin_firestore.Query.DESCENDING).limit(1).stream()
            file_info = None
            for doc in docs:
                file_info = doc.to_dict()
                break
        except Exception:
            file_info = None
        
        file_type = file_info.get('fileType', 'application') if file_info else 'application'
        file_name = file_info.get('fileName', storage['file_name']) if file_info else storage['file_name']
        
        # Gửi notification cho người nhận nếu là DM
        if not is_group:
            try:
                peer_socket = uid_to_socket.get(storage['to_uid'])
                if peer_socket is not None:
                    _send_cmd(peer_socket, {
                        'type': 'FILE_MESSAGE',
                        'fromUid': storage['uid'],
                        'fileURL': file_url,
                        'fileType': file_type,
                        'fileName': file_name,
                        'threadId': conversation_id
                    })
            except Exception:
                pass
        
        # Gửi notification cho các member trong group
        elif is_group:
            try:
                init_firebase_if_needed()
                group_data = db.reference(f'/groups/{storage["group_id"]}').get() or {}
                group_members = group_data.get('members', {})
                
                for member_uid in group_members.keys():
                    if member_uid == storage['uid']:
                        continue
                    try:
                        member_socket = uid_to_socket.get(member_uid)
                        if member_socket is not None:
                            _send_cmd(member_socket, {
                                'type': 'FILE_MESSAGE',
                                'groupId': storage['group_id'],
                                'senderUid': storage['uid'],
                                'fileURL': file_url,
                                'fileType': file_type,
                                'fileName': file_name
                            })
                    except Exception:
                        pass
            except Exception:
                pass
        
        _send_cmd(conn, { 
            'type': 'FILE_SENT', 
            'ok': True, 
            'clientMsgId': client_msg_id, 
            'fileURL': file_url,
            'fileType': file_type,
            'fileName': file_name,
            'conversationId': conversation_id
        })
        
    except Exception as e:
        print(f"[FILE] SEND_FILE_END error: {e}")
        import traceback
        traceback.print_exc()
        _send_cmd(conn, { 'type': 'FILE_SENT', 'ok': False, 'clientMsgId': client_msg_id, 'error': str(e) })


# =====================
# Video call signaling 
# =====================

def _new_call_id() -> str:
    """Tạo call_id ngắn gọn cho mỗi cuộc gọi video."""
    import uuid
    return uuid.uuid4().hex


def _cmd_call_invite(conn, obj: dict):
    uid = _require_uid(conn)
    to_uid = (obj.get('toUid') or '').strip()

    if not uid or not to_uid or uid == to_uid:
        _send_cmd(conn, {
            "type": "CALL_INVITE_SENT",
            "ok": False,
            "error": "invalid_params"
        })
        return

    call_id = _new_call_id()

    # Lưu trạng thái cuộc gọi
    with active_calls_lock:
        active_calls[call_id] = {
            "caller_uid": uid,
            "callee_uid": to_uid,
            "state": "ringing"
        }

    # Thử gửi thông báo tới callee nếu online
    peer_socket = uid_to_socket.get(to_uid)
    if peer_socket is not None:
        _send_cmd(peer_socket, {
            "type": "CALL_INCOMING",
            "callId": call_id,
            "fromUid": uid,
            "signalPath": f"/webrtc_calls/{call_id}"
        })

    # Trả về cho caller
    _send_cmd(conn, {
        "type": "CALL_INVITE_SENT",
        "ok": True,
        "callId": call_id,
        "toUid": to_uid,
        "signalPath": f"/webrtc_calls/{call_id}"
    })


def _cmd_call_accept(conn, obj: dict):
    uid = _require_uid(conn)
    call_id = (obj.get("callId") or "").strip()

    if not uid or not call_id:
        _send_cmd(conn, {
            "type": "CALL_ACCEPT_OK",
            "ok": False,
            "error": "missing_params"
        })
        return

    with active_calls_lock:
        call = active_calls.get(call_id)
        if not call:
            _send_cmd(conn, {
                "type": "CALL_ACCEPT_OK",
                "ok": False,
                "error": "call_not_found"
            })
            return
        if call.get("callee_uid") != uid:
            _send_cmd(conn, {
                "type": "CALL_ACCEPT_OK",
                "ok": False,
                "error": "not_callee"
            })
            return
        call["state"] = "active"
        caller_uid = call.get("caller_uid")

    # Thông báo cho caller
    caller_socket = uid_to_socket.get(caller_uid)
    if caller_socket is not None:
        _send_cmd(caller_socket, {
            "type": "CALL_ACCEPTED",
            "callId": call_id,
            "peerUid": uid,
            "signalPath": f"/webrtc_calls/{call_id}"
        })

    # Acknowledge cho callee
    _send_cmd(conn, {
        "type": "CALL_ACCEPT_OK",
        "ok": True,
        "callId": call_id,
        "peerUid": caller_uid,
        "signalPath": f"/webrtc_calls/{call_id}"
    })


def _cmd_call_reject(conn, obj: dict):
    uid = _require_uid(conn)
    call_id = (obj.get("callId") or "").strip()
    reason = (obj.get("reason") or "").strip()  # ví dụ: "busy"

    if not uid or not call_id:
        _send_cmd(conn, {
            "type": "CALL_REJECT_OK",
            "ok": False,
            "error": "missing_params"
        })
        return

    with active_calls_lock:
        call = active_calls.get(call_id)
        if not call:
            _send_cmd(conn, {
                "type": "CALL_REJECT_OK",
                "ok": False,
                "error": "call_not_found"
            })
            return
        # Cho phép chỉ callee hoặc caller reject
        caller_uid = call.get("caller_uid")
        callee_uid = call.get("callee_uid")
        if uid not in (caller_uid, callee_uid):
            _send_cmd(conn, {
                "type": "CALL_REJECT_OK",
                "ok": False,
                "error": "not_participant"
            })
            return
        # Xoá cuộc gọi
        active_calls.pop(call_id, None)

    # Xác định người còn lại để báo
    other_uid = callee_uid if uid == caller_uid else caller_uid
    other_socket = uid_to_socket.get(other_uid)
    if other_socket is not None:
        payload = {
            "type": "CALL_REJECTED",
            "callId": call_id,
            "fromUid": uid,
        }
        if reason:
            payload["reason"] = reason
        _send_cmd(other_socket, payload)

    _send_cmd(conn, {
        "type": "CALL_REJECT_OK",
        "ok": True,
        "callId": call_id
    })


def _cmd_call_end(conn, obj: dict):
    uid = _require_uid(conn)
    call_id = (obj.get("callId") or "").strip()

    if not uid or not call_id:
        _send_cmd(conn, {
            "type": "CALL_END_OK",
            "ok": False,
            "error": "missing_params"
        })
        return

    with active_calls_lock:
        call = active_calls.get(call_id)
        if not call:
            _send_cmd(conn, {
                "type": "CALL_END_OK",
                "ok": False,
                "error": "call_not_found"
            })
            return
        caller_uid = call.get("caller_uid")
        callee_uid = call.get("callee_uid")
        if uid not in (caller_uid, callee_uid):
            _send_cmd(conn, {
                "type": "CALL_END_OK",
                "ok": False,
                "error": "not_participant"
            })
            return
        # Xoá cuộc gọi
        active_calls.pop(call_id, None)

    other_uid = callee_uid if uid == caller_uid else caller_uid
    other_socket = uid_to_socket.get(other_uid)
    if other_socket is not None:
        _send_cmd(other_socket, {
            "type": "CALL_ENDED",
            "callId": call_id,
            "fromUid": uid
        })

    _send_cmd(conn, {
        "type": "CALL_END_OK",
        "ok": True,
        "callId": call_id
    })

