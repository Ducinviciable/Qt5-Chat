import json
import socket

try:
    from Server.firebase_admin_utils import verify_id_token
    from Server.state import clients, clients_lock, socket_to_user, socket_to_uid, uid_to_socket
    from Server.commands import handle_command_line as commands_handle
except Exception:
    from firebase_admin_utils import verify_id_token
    from state import clients, clients_lock, socket_to_user, socket_to_uid, uid_to_socket
    from commands import handle_command_line as commands_handle


def broadcast(message: str, exclude_socket: socket.socket | None = None):
    with clients_lock:
        dead_clients = []
        for s in clients:
            if exclude_socket is not None and s is exclude_socket:
                continue
            try:
                s.sendall((message + "\n").encode('utf-8'))
            except Exception:
                dead_clients.append(s)
        for s in dead_clients:
            try:
                clients.remove(s)
                socket_to_user.pop(s, None)
            except ValueError:
                pass


def handle_client(conn: socket.socket, addr):
    try:
        conn.settimeout(15.0)
        buffer = b''
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                raise ConnectionAbortedError('No data during auth')
            buffer += chunk
            nl_index = buffer.find(b"\n")
            if nl_index == -1:
                if len(buffer) > 8192:
                    raise ConnectionAbortedError('Auth line too large')
                continue
            line = buffer[:nl_index]
            buffer = buffer[nl_index + 1:]
            try:
                text = line.decode('utf-8', errors='replace')
            except Exception:
                text = ''
            if not text.startswith('AUTH '):
                conn.sendall(b"AUTH_ERR Invalid handshake\n")
                raise ConnectionAbortedError('Invalid handshake')
            id_token = text[5:].strip()
            ok, label, uid, email, name = verify_id_token(id_token)
            if not ok:
                err_line = f"AUTH_ERR {label}\n".encode('utf-8', errors='replace')
                conn.sendall(err_line)
                raise ConnectionAbortedError('Auth failed')
            conn.sendall(b"AUTH_OK\n")
            break

        conn.settimeout(None)

        with clients_lock:
            if conn not in clients:
                clients.append(conn)
            socket_to_user[conn] = label
            try:
                conn._chat_uid = uid  
            except Exception:
                pass
            try:
                socket_to_uid[conn] = uid
                uid_to_socket[uid] = conn
            except Exception:
                pass
        try:
            from Server.firebase_admin_utils import ensure_user_profile as _ensure
        except Exception:
            from firebase_admin_utils import ensure_user_profile as _ensure
        try:
            _ensure(uid, email, name)
        except Exception:
            pass

        welcome = f"[Server] Welcome {label} joined"
        print(welcome)
        broadcast(welcome, exclude_socket=None)
        buffer = buffer if isinstance(buffer, (bytes, bytearray)) else b''
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk

            while True:
                nl_index = buffer.find(b"\n")
                if nl_index != -1:
                    line = buffer[:nl_index]
                    buffer = buffer[nl_index + 1:]
                    try:
                        text = line.decode('utf-8', errors='replace')
                    except Exception:
                        text = '[binary data]'
                    if text.startswith('CMD '):
                        try:
                            obj = json.loads(text[4:])
                        except Exception as e:
                            try:
                                conn.sendall(("CMD {\"type\":\"ERROR\",\"message\":\"invalid_json\"}\n").encode('utf-8'))
                            except Exception:
                                pass
                            continue
                        
                        try:
                            print(f"[CMD] raw line={text}")
                        except Exception:
                            pass
                        
                        try:
                            commands_handle(conn, obj)
                        except Exception as e:
                            try:
                                err = { 'type': 'ERROR', 'message': f'cmd_failed: {e}' }
                                conn.sendall(("CMD " + json.dumps(err) + "\n").encode('utf-8'))
                            except Exception:
                                pass
                        continue
                    if text.lower() == 'exit':
                        raise ConnectionAbortedError('Client requested exit')
                    sender = socket_to_user.get(conn, str(addr))
                    print(f"{sender}: {text}")
                    broadcast(f"{sender}: {text}", exclude_socket=conn)
                    continue
                else:
                    if len(buffer) >= 1024:
                        try:
                            text = buffer.decode('utf-8', errors='replace')
                        except Exception:
                            text = ''
                        if text:
                            if text.startswith('CMD '):
                                try:
                                    obj = json.loads(text[4:])
                                    commands_handle(conn, obj)
                                except Exception as e:
                                    try:
                                        err = { 'type': 'ERROR', 'message': f'cmd_failed: {e}' }
                                        conn.sendall(("CMD " + json.dumps(err) + "\n").encode('utf-8'))
                                    except Exception:
                                        pass
                                buffer = b''
                                continue
                            sender = socket_to_user.get(conn, str(addr))
                            print(f"{sender}: {text}")
                            broadcast(f"{sender}: {text}", exclude_socket=conn)
                            buffer = b''
                            continue
                    break
    except ConnectionAbortedError:
        pass
    except Exception as exc:
        print(f"Error with {addr}: {exc}")
    finally:
        try:
            conn.close()
        finally:
            name = socket_to_user.get(conn)
            with clients_lock:
                while True:
                    try:
                        clients.remove(conn)
                    except ValueError:
                        break
                socket_to_user.pop(conn, None)
                try:
                    socket_to_uid.pop(conn, None)
                except Exception:
                    pass
                try:
                    # Remove by value if matching
                    for k, v in list(uid_to_socket.items()):
                        if v is conn:
                            uid_to_socket.pop(k, None)
                    
                except Exception:
                    pass
            left = f"[Server] {(name or str(addr))} left"
            print(left)
            broadcast(left, exclude_socket=None)


