import socket
import threading

try:
    from Server.handler import handle_client
    from Server.state import clients, clients_lock
except Exception:
    from handler import handle_client
    from state import clients, clients_lock

# Server Configuration
def run_server(host: str = '0.0.0.0', port: int = 8080):
    host_Server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # Dòng lệnh TCP
    host_Server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    host_Server.bind((host, port))
    host_Server.listen(5)

    print(f"Server is listening on port {port}...")

    try:
        while True:
            conn, addr = host_Server.accept() # Accept a connection from a client / Hướng kết nối từ client
            print(f"Connection from {addr} has been established!")
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("Shutting down server...")
    finally:
        with clients_lock:
            for c in clients:
                try:
                    c.close()
                except Exception:
                    pass
            clients.clear()
        host_Server.close()


if __name__ == '__main__':
    run_server()


