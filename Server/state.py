import threading

clients = []
clients_lock = threading.Lock()
socket_to_user = {}  # email/uid/displayName
socket_to_uid = {}   # socket/uid
uid_to_socket = {}   # uid/socket

# File upload (chunked) state
file_chunks_storage = {}
file_chunks_lock = threading.Lock()

# Video call state "ringing" | "active" | "ended"
active_calls = {}
active_calls_lock = threading.Lock()

