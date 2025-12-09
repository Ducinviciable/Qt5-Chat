import sys
import socket
import json
import time
import os
import requests
import tempfile
import base64

# Add parent directory to path for imports
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

import qtawesome as qta
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLineEdit, 
                             QPushButton, QLabel, QHBoxLayout, QSplitter, 
                             QListWidget, QListWidgetItem, QScrollArea, QSizePolicy,
                             QFrame, QSpacerItem, QMessageBox, QTabWidget, QFileDialog, QMenu,
                             QProgressDialog, QCheckBox)
from PyQt5.QtGui import QFont, QColor, QDesktopServices
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QThread, QObject, QUrl, QTimer, QTime
from widgets.emoji_picker import EmojiPicker
from widgets.file_message_widgets import (
    create_image_widget,
    create_audio_widget,
    create_file_widget,
)
from voice.recorder import AudioRecorder, PYAUDIO_AVAILABLE
from voice.player import VoicePlayer
try:
    from Client.video_call_ui import VideoCallWindow
except Exception as e:
    print(f"[ui_chat] Failed to import VideoCallWindow from Client.video_call_ui: {e}")
    try:
        from video_call_ui import VideoCallWindow
    except Exception as e2:
        print(f"[ui_chat] Failed to import VideoCallWindow from video_call_ui: {e2}")
        VideoCallWindow = None
try:
    from client_upload import upload_file_to_firebase_storage
except Exception:
    try:
        from Client.client_upload import upload_file_to_firebase_storage
    except Exception:
        upload_file_to_firebase_storage = None

# --- WORKER KIỂM TRA FILE TỒN TẠI ---
class FileCheckWorker(QThread):
    check_complete = pyqtSignal(object, bool, str)  # container, exists, file_url
    
    def __init__(self, file_url, container):
        super().__init__()
        self.file_url = file_url
        self.container = container
    
    def run(self):
        try:
            response = requests.head(self.file_url, timeout=10, allow_redirects=True)
            file_exists = response.status_code == 200
            
            if response.status_code == 405:  # Method Not Allowed
                response = requests.get(self.file_url, timeout=10, stream=True)
                file_exists = response.status_code == 200
            
            self.check_complete.emit(self.container, file_exists, self.file_url)
        except requests.exceptions.RequestException as e:
            # Nếu lỗi, coi như file không tồn tại
            print(f"[FileCheck] Error checking file {self.file_url}: {e}")
            self.check_complete.emit(self.container, False, self.file_url)
        except Exception as e:
            print(f"[FileCheck] Unexpected error: {e}")
            self.check_complete.emit(self.container, False, self.file_url)

# --- LỚP XỬ LÝ MẠNG (NETWORK WORKER) ---
class NetworkWorker(QThread):
    message_received = pyqtSignal(str)
    connection_lost = pyqtSignal()
    auth_successful = pyqtSignal()

    def __init__(self, host, port, id_token):
        super().__init__()
        self.host = host
        self.port = port
        self.id_token = id_token
        self.socket = None
        self.is_running = True

    def run(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            
            # Gửi handshake AUTH
            auth_cmd = f"AUTH {self.id_token}\n"
            self.socket.sendall(auth_cmd.encode('utf-8'))
            
            # Đọc phản hồi AUTH
            buffer = b""
            while b"\n" not in buffer:
                chunk = self.socket.recv(1024)
                if not chunk: raise ConnectionError("Connection closed during auth")
                buffer += chunk
            
            line, buffer = buffer.split(b"\n", 1)
            response = line.decode('utf-8').strip()
            
            if response != "AUTH_OK":
                print(f"Auth failed: {response}")
                self.connection_lost.emit()
                return
            self.auth_successful.emit()
            # Vòng lặp nhận tin nhắn chính
            while self.is_running:
                try:
                    chunk = self.socket.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        text = line.decode('utf-8').strip()
                        if text:
                            self.message_received.emit(text)
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Socket error: {e}")
                    break
                    
        except Exception as e:
            print(f"Connection error: {e}")
        
        self.connection_lost.emit()

    def send_data(self, data_str):
        if self.socket:
            try:
                self.socket.sendall((data_str + "\n").encode('utf-8'))
                return True
            except Exception as e:
                print(f"Send error: {e}")
        return False

    def stop(self):
        self.is_running = False
        if self.socket:
            self.socket.close()


# --- CỬA SỔ DANH SÁCH YÊU CẦU KẾT BẠN ---
class FriendRequestsWindow(QWidget):
    def __init__(self, parent_chat):
        super().__init__()
        self.parent_chat = parent_chat # Tham chiếu để gửi lệnh
        self.setWindowTitle("Danh sách kết bạn")
        self.setGeometry(220, 160, 400, 500)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QHBoxLayout()
        icon = QLabel("📩")
        icon.setFont(QFont("Arial", 24))
        title = QLabel("Lời mời kết bạn")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        main_layout.addLayout(header)

        # List Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.requests_layout = QVBoxLayout(self.content_widget)
        self.requests_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll)

    def update_requests(self, requests_data):
        # Xóa cũ
        for i in reversed(range(self.requests_layout.count())): 
            self.requests_layout.itemAt(i).widget().setParent(None)

        for req in requests_data:
            from_email = req.get('fromEmail') or req.get('fromUid') or 'Unknown'
            from_uid = req.get('fromUid')
            self.requests_layout.addWidget(self.create_request_item(from_email, from_uid))

    def create_request_item(self, name, uid):
        row = QFrame()
        row.setStyleSheet("QFrame { background-color: white; border-radius: 5px; border: 1px solid #ddd; }")
        layout = QHBoxLayout(row)
        
        lbl_name = QLabel(name)
        lbl_name.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_name.setStyleSheet("border: none;")
        
        btn_accept = QPushButton("Đồng ý")
        btn_accept.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; padding: 5px; border-radius: 3px; }")
        btn_accept.clicked.connect(lambda: self.parent_chat.send_accept_request(uid))
        
        btn_reject = QPushButton("Xóa")
        btn_reject.setStyleSheet("QPushButton { background-color: #f44336; color: white; border: none; padding: 5px; border-radius: 3px; }")
        btn_reject.clicked.connect(lambda: self.parent_chat.send_reject_request(uid))

        layout.addWidget(lbl_name)
        layout.addStretch()
        layout.addWidget(btn_accept)
        layout.addWidget(btn_reject)
        return row


# --- CỬA SỔ TẠO NHÓM ---
class CreateGroupWindow(QWidget):
    def __init__(self, parent_chat):
        super().__init__()
        self.parent_chat = parent_chat
        self.setWindowTitle("Tạo Nhóm Chat")
        self.setGeometry(250, 200, 500, 600)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # Icon & Title
        icon_label = QLabel("👥")
        icon_label.setFont(QFont("Arial", 40))
        icon_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(icon_label)
        
        title_label = QLabel("Tạo nhóm chat mới")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Tên nhóm
        name_label = QLabel("Tên nhóm:")
        name_label.setFont(QFont("Arial", 12, QFont.Bold))
        main_layout.addWidget(name_label)
        
        self.group_name_input = QLineEdit()
        self.group_name_input.setPlaceholderText("Nhập tên nhóm...")
        self.group_name_input.setFixedHeight(40)
        self.group_name_input.setStyleSheet("padding: 5px; border: 1px solid #ccc; border-radius: 5px;")
        main_layout.addWidget(self.group_name_input)

        # Chọn thành viên
        members_label = QLabel("Chọn thành viên:")
        members_label.setFont(QFont("Arial", 12, QFont.Bold))
        main_layout.addWidget(members_label)

        # Scroll area cho danh sách bạn bè
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(250)
        self.content_widget = QWidget()
        self.friends_layout = QVBoxLayout(self.content_widget)
        self.friends_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll)

        # Nút tạo nhóm
        self.btn_create = QPushButton("Tạo nhóm")
        self.btn_create.setFixedHeight(40)
        self.btn_create.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border-radius: 5px; font-weight: bold; font-size: 14px; } QPushButton:hover { background-color: #43A047; } QPushButton:disabled { background-color: #cccccc; }")
        self.btn_create.clicked.connect(self.do_create_group)
        main_layout.addWidget(self.btn_create)

        # Lưu checkboxes để dễ quản lý
        self.friend_checkboxes = {}  # {uid: checkbox}

    def update_friends_list(self, friends_list):
        """Cập nhật danh sách bạn bè trong dialog."""
        # Xóa checkboxes cũ
        for i in reversed(range(self.friends_layout.count())):
            widget = self.friends_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.friend_checkboxes.clear()

        # Nếu chưa có dữ liệu (None = chưa load lần nào)
        if friends_list is None:
            loading_label = QLabel("Đang tải danh sách bạn bè...")
            loading_label.setAlignment(Qt.AlignCenter)
            loading_label.setStyleSheet("color: #666; padding: 20px; font-style: italic;")
            self.friends_layout.addWidget(loading_label)
            self.btn_create.setEnabled(False)
            return

        # Nếu đã load nhưng danh sách rỗng
        if isinstance(friends_list, list) and len(friends_list) == 0:
            print(f"[CreateGroup] Friends list is empty")
            no_friends_label = QLabel("Chưa có bạn bè nào. Hãy thêm bạn bè trước!")
            no_friends_label.setAlignment(Qt.AlignCenter)
            no_friends_label.setStyleSheet("color: #666; padding: 20px;")
            self.friends_layout.addWidget(no_friends_label)
            self.btn_create.setEnabled(False)
            return

        # Tạo checkbox cho mỗi bạn bè
        print(f"[CreateGroup] Updating friends list with {len(friends_list)} friends")
        for friend in friends_list:
            uid = friend.get('uid', '')
            email = friend.get('email', '') or ''
            display_name = friend.get('displayName', '') or ''
            
            print(f"[CreateGroup] Friend: uid={uid}, email={email}, displayName={display_name}")
            
            if not uid:
                print(f"[CreateGroup] Skipping friend without uid: {friend}")
                continue

            if display_name:
                final_display_name = display_name
            elif email:
                final_display_name = email.split('@')[0] if '@' in email else email
            else:
                final_display_name = uid[:8] + '...' if len(uid) > 8 else uid
            
            print(f"[CreateGroup] Final display name: '{final_display_name}' for uid={uid}")

            row = QFrame()
            row.setStyleSheet("QFrame { background-color: white; border-radius: 5px; border: 1px solid #ddd; padding: 5px; }")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(10, 5, 10, 5)
            
            checkbox = QCheckBox()
            checkbox.setStyleSheet("""
                QCheckBox {
                    font-size: 14px;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #ccc;
                    border-radius: 4px;
                    background-color: white;
                }
                QCheckBox::indicator:checked {
                    background-color: #4CAF50;
                    border: 2px solid #4CAF50;
                }
            """)
            
            # Đảm bảo final_display_name không rỗng
            if not final_display_name or not final_display_name.strip():
                final_display_name = f"User ({uid[:8]}...)" if uid else "Unknown"
            
            name_label = QLabel(final_display_name)
            name_label.setFont(QFont("Arial", 11, QFont.Normal))
            name_label.setWordWrap(False)
            name_label.setStyleSheet("color: #333; padding: 5px 0px; background-color: transparent;")
            name_label.setMinimumHeight(24)
            name_label.setMinimumWidth(100)
            name_label.setText(final_display_name)  # Đảm bảo set text rõ ràng
            
            print(f"[CreateGroup] Created label with text: '{final_display_name}' for uid={uid}")
            
            layout.addWidget(checkbox)
            layout.addSpacing(10) 
            layout.addWidget(name_label, 1)  # Thêm stretch factor để label chiếm không gian
            layout.addStretch()
            
            self.friends_layout.addWidget(row)
            self.friend_checkboxes[uid] = checkbox

        self.btn_create.setEnabled(True)

    def do_create_group(self):
        """Xử lý khi nhấn nút Tạo nhóm."""
        group_name = self.group_name_input.text().strip()
        if not group_name:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập tên nhóm!")
            return

        selected_member_uids = []
        for uid, checkbox in self.friend_checkboxes.items():
            if checkbox.isChecked():
                selected_member_uids.append(uid)

        if not selected_member_uids:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn ít nhất một thành viên!")
            return

        # Gửi command tạo nhóm
        self.parent_chat.send_command({
            'type': 'CREATE_GROUP',
            'name': group_name,
            'memberUids': selected_member_uids
        })

        # Disable nút để tránh tạo nhiều lần
        self.btn_create.setEnabled(False)
        self.btn_create.setText("Đang tạo...")

    def show_group_created(self, success=True, error_msg=''):
        """Được gọi khi nhận response từ server."""
        if success:
            QMessageBox.information(self, "Thành công", "Đã tạo nhóm thành công!")
            self.close()
        else:
            QMessageBox.warning(self, "Lỗi", f"Không thể tạo nhóm: {error_msg}")
            self.btn_create.setEnabled(True)
            self.btn_create.setText("Tạo nhóm")


# --- CỬA SỔ TÌM KIẾM BẠN BÈ ---
class FindFriendWindow(QWidget):
    def __init__(self, parent_chat):
        super().__init__()
        self.parent_chat = parent_chat
        self.setWindowTitle("Tìm Bạn Bè")
        self.setGeometry(200, 200, 500, 400)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # Icon & Title
        icon_label = QLabel("🔍")
        icon_label.setFont(QFont("Arial", 40))
        icon_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(icon_label)
        
        title_label = QLabel("Tìm bạn bè qua Email")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Form
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Nhập email người dùng...")
        self.email_input.setFixedHeight(40)
        self.email_input.setStyleSheet("padding: 5px; border: 1px solid #ccc; border-radius: 20px;")
        main_layout.addWidget(self.email_input)
        
        self.search_button = QPushButton("Tìm kiếm")
        self.search_button.setFixedHeight(40)
        self.search_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; border-radius: 20px; font-weight: bold; } QPushButton:hover { background-color: #1976D2; }")
        self.search_button.clicked.connect(self.do_search)
        main_layout.addWidget(self.search_button)
        
        # Result Area
        self.result_frame = QFrame()
        self.result_frame.hide()
        r_layout = QVBoxLayout(self.result_frame)
        
        self.lbl_result_name = QLabel("")
        self.lbl_result_name.setFont(QFont("Arial", 12, QFont.Bold))
        self.lbl_result_name.setAlignment(Qt.AlignCenter)
        r_layout.addWidget(self.lbl_result_name)
        
        self.btn_add_friend = QPushButton("Gửi lời mời kết bạn")
        self.btn_add_friend.setFixedHeight(35)
        self.btn_add_friend.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 15px;")
        self.btn_add_friend.clicked.connect(self.do_add_friend)
        r_layout.addWidget(self.btn_add_friend)
        
        main_layout.addWidget(self.result_frame)
        self.found_email = None

    def do_search(self):
        email = self.email_input.text().strip()
        if not email: return
        # Gửi lệnh tìm kiếm qua socket của cửa sổ chính
        self.parent_chat.send_command({'type': 'FIND_USER', 'email': email})

    def show_result(self, data):
        if data.get('found'):
            self.found_email = data.get('email')
            name = data.get('displayName') or self.found_email
            self.lbl_result_name.setText(f"Tìm thấy: {name}")
            self.result_frame.show()
            self.btn_add_friend.setEnabled(True)
        else:
            QMessageBox.warning(self, "Thông báo", data.get('error', 'Không tìm thấy người dùng'))
            self.result_frame.hide()

    def do_add_friend(self):
        if self.found_email:
            self.parent_chat.send_command({'type': 'SEND_FRIEND_REQUEST', 'toEmail': self.found_email})
            self.btn_add_friend.setEnabled(False)
            self.btn_add_friend.setText("Đã gửi yêu cầu")


# --- CỬA SỔ CHAT CHÍNH ---
class ChatWindow(QWidget):
    def __init__(self, host='localhost', port=8080, id_token='', user_email=''):
        super().__init__()
        self.setWindowTitle("Chat App")
        self.setGeometry(50, 50, 1000, 700) 
        
        self.current_user_email = user_email
        self.host = host
        self.port = port
        self.id_token = id_token
        
        # Dữ liệu runtime
        self.contact_buttons = []
        self.current_selected_button = None
        self.current_chat_uid = None 
        self.current_chat_is_group = False
        self._current_group_members = []
        self.current_user_uid = None 
        self.find_friend_window = None 
        self.friend_requests_window = None
        self.create_group_window = None
        self.friends_list = None  
        
        # Voice recording
        self.audio_recorder = None
        self.is_recording = False
        self.recording_timer = None
        self.recording_duration = 0
        self.recording_file = None
        
        # Voice playback
        self.voice_player = VoicePlayer(self)

        # --- Video call state ---
        self.current_call_id = None           # callId hiện tại (nếu đang trong cuộc gọi)
        self.current_call_signal_path = None  
        self.current_call_peer_uid = None     # UID của người đang gọi cùng
        self.current_call_is_caller = False   
        self.video_call_window = None         
        self._call_ringing_timer = None       # QTimer timeout khi đang đổ chuông (caller side)
        
        # Upload progress
        self._upload_progress_dialog = None 
        self._uploading_file_name = None  
        self._upload_client_msg_id = None  
        
        self._file_check_workers = []
        
        self._file_check_cache = {}  # {file_url: exists (bool)}
        
        self.setup_ui()
        
        # Khởi động kết nối mạng
        self.network = NetworkWorker(self.host, self.port, self.id_token)
        self.connect_signals()
        # self.network.auth_successful.connect(self.on_auth_success)
        # self.network.message_received.connect(self.handle_server_message)
        # self.network.connection_lost.connect(self.handle_connection_lost)
        self.network.start()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Top Header ---
        top_header = QWidget()
        top_header.setFixedHeight(70)
        top_header.setStyleSheet("background-color: #f5f5f5; border-bottom: 1px solid #ddd;")
        top_layout = QHBoxLayout(top_header)
        
        icon = QLabel("💬")
        icon.setFont(QFont("Arial", 20))
        
        self.lbl_my_name = QLabel(self.current_user_email or "Me")
        self.lbl_my_name.setFont(QFont("Arial", 14, QFont.Bold))
        
        self.btn_requests = QPushButton("🔔 Yêu cầu")
        self.btn_requests.clicked.connect(self.open_friend_requests)
        
        self.btn_find = QPushButton("➕ Thêm bạn")
        self.btn_find.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 5px 10px; border-radius: 5px;")
        self.btn_find.clicked.connect(self.open_find_friend)

        self.btn_create_group = QPushButton("👥 Tạo nhóm")
        self.btn_create_group.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; padding: 5px 10px; border-radius: 5px;")
        self.btn_create_group.clicked.connect(self.open_create_group)

        top_layout.addWidget(icon)
        top_layout.addWidget(self.lbl_my_name)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_requests)
        top_layout.addWidget(self.btn_find)
        top_layout.addWidget(self.btn_create_group)
        
        main_layout.addWidget(top_header)

        # --- Main Splitter ---
        splitter = QSplitter(Qt.Horizontal)
        
        # KHUNG TRÁI: DANH SÁCH BẠN BÈ
        left_frame = QWidget()
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Tabs
        tab_layout = QHBoxLayout()
        self.btn_tab_user = QPushButton("Người dùng")
        self.btn_tab_user.setFixedHeight(40)
        self.btn_tab_user.setStyleSheet("background-color: #00BFFF; color: white; border: none;")
        self.btn_tab_group = QPushButton("Nhóm")
        self.btn_tab_group.setFixedHeight(40)
        
        tab_layout.addWidget(self.btn_tab_user)
        tab_layout.addWidget(self.btn_tab_group)
        left_layout.addLayout(tab_layout)

        # List
        self.contact_list = QListWidget()
        self.contact_list.setStyleSheet("border: none;")
        self.contact_list.setMinimumWidth(250)
        left_layout.addWidget(self.contact_list)
        
        splitter.addWidget(left_frame)

        # KHUNG PHẢI: CHAT
        right_frame = QWidget()
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Chat Header
        self.chat_header = QWidget()
        self.chat_header.setFixedHeight(60)
        self.chat_header.setStyleSheet("background-color: white; border-bottom: 1px solid #eee;")
        ch_layout = QHBoxLayout(self.chat_header)
        
        self.lbl_chat_name = QLabel("Chọn một người bạn để chat")
        self.lbl_chat_name.setFont(QFont("Arial", 12, QFont.Bold))
        ch_layout.addWidget(self.lbl_chat_name)
        ch_layout.addStretch()

        # Nút gọi video (chỉ dùng cho chat 1-1, sẽ enable khi chọn user)
        self.btn_video_call = QPushButton("📹 Video")
        self.btn_video_call.setFixedHeight(32)
        self.btn_video_call.setEnabled(False)
        self.btn_video_call.setToolTip("Gọi video với người đang chat")
        self.btn_video_call.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border-radius: 16px;
                padding: 4px 12px;
                font-weight: bold;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QPushButton:hover:!disabled {
                background-color: #43A047;
            }
        """)
        self.btn_video_call.clicked.connect(self.start_video_call)
        ch_layout.addWidget(self.btn_video_call)
        
        right_layout.addWidget(self.chat_header)

        # Group members panel (ẩn khi không trong phòng nhóm)
        self.group_members_panel = QWidget()
        self.group_members_panel.setStyleSheet("background-color: #f9f9f9; border-bottom: 1px solid #eee;")
        gm_layout = QHBoxLayout(self.group_members_panel)
        gm_layout.setContentsMargins(15, 5, 15, 5)
        gm_layout.setSpacing(10)
        gm_title = QLabel("Thành viên:")
        gm_title.setFont(QFont("Arial", 10, QFont.Bold))
        self.group_members_value_label = QLabel("Chưa có dữ liệu")
        self.group_members_value_label.setWordWrap(True)
        self.group_members_value_label.setStyleSheet("color: #555;")
        gm_layout.addWidget(gm_title)
        gm_layout.addWidget(self.group_members_value_label, 1)
        
        # Nút rời nhóm
        self.btn_leave_group = QPushButton("Rời nhóm")
        self.btn_leave_group.setFixedHeight(30)
        self.btn_leave_group.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border-radius: 15px;
                padding: 5px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.btn_leave_group.clicked.connect(self.leave_group)
        gm_layout.addWidget(self.btn_leave_group)
        
        self.group_members_panel.hide()
        right_layout.addWidget(self.group_members_panel)

        # Chat Area
        self.message_area = QScrollArea()
        self.message_area.setWidgetResizable(True)
        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setAlignment(Qt.AlignTop)
        self.message_area.setWidget(self.message_container)
        right_layout.addWidget(self.message_area)

        # Emoji Picker component
        self.emoji_picker = EmojiPicker(self)
        self.emoji_picker.emoji_selected.connect(self.insert_emoji)
        right_layout.addWidget(self.emoji_picker)

        # Input Area
        input_frame = QWidget()
        input_frame.setFixedHeight(60)
        input_layout = QHBoxLayout(input_frame)
        
        # Nút mở emoji picker - Sử dụng qtawesome icon
        self.btn_emoji = QPushButton()
        self.btn_emoji.setFixedSize(40, 40)
        try:
            self.btn_emoji.setIcon(qta.icon('fa.smile-o', color='#666'))
            self.btn_emoji.setIconSize(QSize(20, 20))
        except Exception as e:
            print(f"Warning: Could not load emoji icon: {e}")
            self.btn_emoji.setText("😀")
        self.btn_emoji.setToolTip("Chọn emoji")
        self.btn_emoji.setStyleSheet("""
            QPushButton { 
                border: 1px solid #ddd; 
                border-radius: 5px; 
                background-color: white; 
            } 
            QPushButton:hover { 
                background-color: #f0f0f0; 
                border: 1px solid #2196F3; 
            }
        """)
        self.btn_emoji.clicked.connect(self.toggle_emoji_picker)
        
        # Nút upload file - Sử dụng qtawesome icon
        self.btn_upload = QPushButton()
        self.btn_upload.setFixedSize(40, 40)
        try:
            self.btn_upload.setIcon(qta.icon('fa.paperclip', color='#666'))
            self.btn_upload.setIconSize(QSize(20, 20))
        except Exception as e:
            print(f"Warning: Could not load upload icon: {e}")
            self.btn_upload.setText("📎")
        self.btn_upload.setToolTip("Gửi file")
        self.btn_upload.setStyleSheet("""
            QPushButton { 
                border: 1px solid #ddd; 
                border-radius: 5px; 
                background-color: white; 
            } 
            QPushButton:hover { 
                background-color: #f0f0f0; 
                border: 1px solid #2196F3; 
            }
        """)
        self.btn_upload.clicked.connect(self.upload_file)
        
        # Nút ghi âm - Sử dụng qtawesome icon
        self.btn_voice = QPushButton()
        self.btn_voice.setFixedSize(40, 40)
        try:
            self.btn_voice.setIcon(qta.icon('fa.microphone', color='#666'))
            self.btn_voice.setIconSize(QSize(20, 20))
        except Exception as e:
            print(f"Warning: Could not load voice icon: {e}")
            self.btn_voice.setText("🎤")
        self.btn_voice.setToolTip("Ghi âm tin nhắn thoại")
        self.btn_voice.setStyleSheet("""
            QPushButton { 
                border: 1px solid #ddd; 
                border-radius: 5px; 
                background-color: white; 
            } 
            QPushButton:hover { 
                background-color: #f0f0f0; 
                border: 1px solid #2196F3; 
            }
            QPushButton:pressed {
                background-color: #ffebee;
                border: 1px solid #f44336;
            }
        """)
        self.btn_voice.setCheckable(True)  # Có thể nhấn giữ
        self.btn_voice.pressed.connect(self.start_recording)
        self.btn_voice.released.connect(self.stop_recording)
        
        # Label hiển thị thời gian ghi âm
        self.recording_label = QLabel("")
        self.recording_label.setStyleSheet("color: #f44336; font-weight: bold;")
        self.recording_label.hide()
        
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Nhập tin nhắn...")
        self.msg_input.returnPressed.connect(self.send_message)
        
        # Nút gửi - Sử dụng qtawesome icon
        self.btn_send = QPushButton()
        self.btn_send.setFixedSize(40, 40)
        try:
            self.btn_send.setIcon(qta.icon('fa.paper-plane', color='white'))
            self.btn_send.setIconSize(QSize(18, 18))
        except Exception as e:
            print(f"Warning: Could not load send icon: {e}")
            self.btn_send.setText("➤")
        self.btn_send.setToolTip("Gửi tin nhắn")
        self.btn_send.setStyleSheet("""
            QPushButton { 
                border: 1px solid #2196F3; 
                border-radius: 5px; 
                background-color: #2196F3; 
                color: white;
            } 
            QPushButton:hover { 
                background-color: #1976D2; 
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        self.btn_send.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.btn_emoji)
        input_layout.addWidget(self.btn_upload)
        input_layout.addWidget(self.btn_voice)
        input_layout.addWidget(self.msg_input)
        input_layout.addWidget(self.btn_send)
        
        # Thêm recording label vào input frame (sẽ hiển thị khi đang ghi)
        recording_layout = QHBoxLayout()
        recording_layout.addWidget(self.recording_label)
        recording_layout.addStretch()
        input_layout.addLayout(recording_layout)
        
        right_layout.addWidget(input_frame)
        
        splitter.addWidget(right_frame)
        splitter.setSizes([300, 700])
        main_layout.addWidget(splitter)

    # --- LOGIC MẠNG & XỬ LÝ LỆNH ---
    def connect_signals(self):
        # Kết nối sự kiện AUTH thành công
        self.network.auth_successful.connect(self.on_auth_success)
        self.network.message_received.connect(self.handle_server_message)
        self.network.connection_lost.connect(self.handle_connection_lost)
        self.btn_tab_user.clicked.connect(self.load_users)
        self.btn_tab_group.clicked.connect(self.load_groups)

    def on_auth_success(self):
        """Hàm được gọi khi xác thực socket thành công."""
        print("[Network] Xác thực socket thành công. Đang tải danh sách bạn bè...")
        self.send_command({'type': 'LIST_FRIENDS'})

    def send_command(self, cmd_dict):
        """Gửi lệnh JSON xuống socket"""
        cmd_str = "CMD " + json.dumps(cmd_dict)
        self.network.send_data(cmd_str)

    def handle_server_message(self, text):
        """Router xử lý các tin nhắn từ server"""
        if text.startswith("CMD "):
            try:
                data = json.loads(text[4:])
                self.process_command(data)
            except Exception as e:
                print(f"JSON parse error: {e}")
        else:
            print(f"Server: {text}")

    def handle_connection_lost(self):
        QMessageBox.critical(self, "Lỗi", "Mất kết nối đến server!")
        self.close()
    # Handle type of command
    def process_command(self, data):
        cmd_type = data.get('type')
        
        if cmd_type == 'FIND_USER_RESULT':
            if self.find_friend_window:
                self.find_friend_window.show_result(data)
                
        elif cmd_type == 'FRIENDS':
            friends = data.get('friends', [])
            print(f"[System] Đã tải thành công {len(friends)} bạn bè.")
            self.friends_list = friends  # Lưu danh sách bạn bè để dùng trong dialog tạo nhóm
            self.populate_list(friends, is_group=False) # Dùng hàm chung
            # Cập nhật danh sách trong dialog tạo nhóm nếu đang mở
            if self.create_group_window and self.create_group_window.isVisible():
                self.create_group_window.update_friends_list(friends)

        elif cmd_type == 'GROUPS': # <--- XỬ LÝ LỆNH MỚI
            groups = data.get('groups', [])
            print(f"[System] Đã tải thành công {len(groups)} nhóm.")
            self.populate_list(groups, is_group=True)
            
        elif cmd_type == 'FRIEND_REQUESTS':
            reqs = data.get('requests', [])
            if self.friend_requests_window:
                self.friend_requests_window.update_requests(reqs)
            # Cập nhật badge số lượng nếu cần
            self.btn_requests.setText(f"🔔 Yêu cầu ({len(reqs)})")

        elif cmd_type == 'DM':
            # Nhận tin nhắn từ người khác
            sender_uid = data.get('fromUid')
            text = data.get('text')
            if sender_uid == self.current_chat_uid:
                self.add_message_bubble(text, is_self=False)
            else:
                # TODO: Hiển thị notif
                pass

        elif cmd_type == 'DM_HISTORY':
            # Nhận lịch sử chat
            msgs = data.get('messages', [])
            me_uid = data.get('meUid')
            # Lưu UID của chính mình nếu chưa có
            if me_uid and not self.current_user_uid:
                self.current_user_uid = me_uid
            
            # Xóa chat cũ
            for i in reversed(range(self.message_layout.count())): 
                self.message_layout.itemAt(i).widget().setParent(None)
            
            for m in msgs:
                is_me = (m.get('senderUid') == me_uid)
                # Kiểm tra nếu là message có file
                if m.get('fileURL'):
                    file_url = m.get('fileURL', '')
                    # Kiểm tra cache trước - nếu file đã biết là không tồn tại thì bỏ qua
                    if file_url in self._file_check_cache and not self._file_check_cache[file_url]:
                        # File đã được kiểm tra và không tồn tại - bỏ qua message này
                        print(f"[FileCheck] Bỏ qua message với file không tồn tại (từ cache): {file_url}")
                        continue
                    
                    self.add_file_message({
                        'fileType': m.get('fileType', 'application'),
                        'fileURL': file_url,
                        'fileName': m.get('fileName', 'Unknown')
                    }, is_self=is_me)
                else:
                    self.add_message_bubble(m.get('text'), is_self=is_me)
        
        elif cmd_type == 'FILE_MESSAGE':
            # Nhận file message từ người khác
            sender_uid = data.get('fromUid') or data.get('senderUid')
            file_url = data.get('fileURL', '')
            file_name = data.get('fileName', 'Unknown')
            file_type = data.get('fileType', 'application')
            
            if sender_uid == self.current_chat_uid or (self.current_chat_is_group and data.get('groupId') == self.current_chat_uid):
                self.add_file_message({
                    'fileType': file_type,
                    'fileURL': file_url,
                    'fileName': file_name
                }, is_self=False)
        
        elif cmd_type == 'FILE_SENT':
            # Response từ server khi upload thành công
            client_msg_id = data.get('clientMsgId', '')
            
            # Đóng loading dialog
            self._hide_upload_progress()
            
            if data.get('ok'):
                file_url = data.get('fileURL', '')
                file_type = data.get('fileType', 'application')
                file_name = data.get('fileName', 'Unknown')
                conversation_id = data.get('conversationId', '')
                
                # Kiểm tra nếu đang chat với conversation này
                should_display = False
                if conversation_id:
                    if self.current_chat_is_group and conversation_id == self.current_chat_uid:
                        # Đang chat nhóm, conversation_id = group_id
                        should_display = True
                    elif not self.current_chat_is_group and self.current_chat_uid:
                        # DM: conversation_id là thread_id
                        # Thread_id được tạo từ uid_a và uid_b, sắp xếp alphabetically
                        # Tạo thread_id từ current_user_uid và current_chat_uid để so sánh
                        if self.current_user_uid:
                            thread_id_a = f"{self.current_user_uid}__{self.current_chat_uid}"
                            thread_id_b = f"{self.current_chat_uid}__{self.current_user_uid}"
                            if conversation_id == thread_id_a or conversation_id == thread_id_b:
                                should_display = True
                        else:
                            # Nếu chưa có current_user_uid, hiển thị luôn (sẽ được fix khi load history)
                            should_display = True
                
                if should_display:
                    # Hiển thị file message
                    self.add_file_message({
                        'fileType': file_type,
                        'fileURL': file_url,
                        'fileName': file_name
                    }, is_self=True)
                
                print(f"[File] Upload thành công: {file_url}")
                # Cuộn xuống cuối
                QApplication.processEvents()
                self.message_area.verticalScrollBar().setValue(self.message_area.verticalScrollBar().maximum())
            else:
                error_msg = data.get('error', 'Unknown error')
                QMessageBox.warning(self, "Lỗi", f"Không thể upload file: {error_msg}")
                
        elif cmd_type == 'FRIEND_REQUEST_SENT':
            if data.get('ok'):
                QMessageBox.showinfo(self, "Thành công", "Đã gửi lời mời kết bạn!")
            else:
                QMessageBox.warning(self, "Lỗi", data.get('error', 'Lỗi không xác định'))
                
        elif cmd_type == 'FRIEND_REQUEST_ACCEPTED':
            self.send_command({'type': 'LIST_FRIENDS'}) # Refresh list
            if self.friend_requests_window:
                self.send_command({'type': 'FRIEND_REQUESTS'})

        elif cmd_type == 'GROUP_CREATED':
            if data.get('ok'):
                if self.create_group_window:
                    self.create_group_window.show_group_created(success=True)
                # Refresh danh sách nhóm
                self.send_command({'type': 'LIST_GROUPS'})
            else:
                error_msg = data.get('error', 'Lỗi không xác định')
                if self.create_group_window:
                    self.create_group_window.show_group_created(success=False, error_msg=error_msg)

        elif cmd_type == 'GROUP_HISTORY': # <--- THÊM LOGIC NÀY
            # Xử lý lịch sử chat Nhóm
            msgs = data.get('messages', [])
            me_uid = data.get('meUid')
            # Lưu UID của chính mình nếu chưa có
            if me_uid and not self.current_user_uid:
                self.current_user_uid = me_uid
            
            # Xóa chat cũ (Lặp lại logic xóa)
            for i in reversed(range(self.message_layout.count())): 
                self.message_layout.itemAt(i).widget().setParent(None)

            for m in msgs:
                sender_uid = m.get('senderUid')
                is_me = (sender_uid == me_uid) if me_uid else False
                
                # Bỏ qua tin nhắn hệ thống
                if m.get('system'):
                    continue
                
                # Kiểm tra nếu là message có file
                if m.get('fileURL'):
                    file_url = m.get('fileURL', '')
                    # Kiểm tra cache trước - nếu file đã biết là không tồn tại thì bỏ qua
                    if file_url in self._file_check_cache and not self._file_check_cache[file_url]:
                        # File đã được kiểm tra và không tồn tại - bỏ qua message này
                        print(f"[FileCheck] Bỏ qua message với file không tồn tại (từ cache): {file_url}")
                        continue
                    
                    self.add_file_message({
                        'fileType': m.get('fileType', 'application'),
                        'fileURL': file_url,
                        'fileName': m.get('fileName', 'Unknown')
                    }, is_self=is_me)
                elif m.get('text'):  # Chỉ hiển thị nếu có text
                    self.add_message_bubble(m.get('text'), is_me)

        elif cmd_type == 'GROUP_MEMBERS':
            if not data.get('ok'):
                error_msg = data.get('error')
                if error_msg:
                    print(f"[Group] Không thể tải danh sách thành viên: {error_msg}")
                return
            group_id = data.get('groupId')
            if not self.current_chat_is_group or group_id != self.current_chat_uid:
                return
            members = data.get('members', [])
            self._current_group_members = members
            self._update_group_members_panel(members)
            
        elif cmd_type == 'LEAVE_GROUP_OK':
            # Xử lý response khi rời nhóm
            if data.get('ok'):
                group_id = data.get('groupId')
                print(f"[Group] Đã rời nhóm thành công: {group_id}")
                
                # Nếu đang chat nhóm này, đóng chat
                if self.current_chat_is_group and self.current_chat_uid == group_id:
                    self.current_chat_uid = None
                    self.current_chat_is_group = False
                    self.lbl_chat_name.setText("Chọn một người bạn để chat")
                    self.group_members_panel.hide()
                    
                    # Xóa tin nhắn
                    for i in reversed(range(self.message_layout.count())):
                        widget = self.message_layout.itemAt(i).widget()
                        if widget is not None:
                            widget.deleteLater()
                
                # Reload danh sách nhóm
                self.load_groups()
                
                # Hiển thị thông báo
                QMessageBox.information(self, "Thông báo", "Bạn đã rời nhóm thành công!")
            else:
                error_msg = data.get('error', 'Unknown error')
                QMessageBox.warning(self, "Lỗi", f"Không thể rời nhóm: {error_msg}")

        # --- VIDEO CALL SIGNALING (PHASE 1) ---
        elif cmd_type == 'CALL_INCOMING':
            # Có cuộc gọi đến từ người khác
            call_id = data.get('callId')
            from_uid = data.get('fromUid')
            signal_path = data.get('signalPath') or (f"/webrtc_calls/{call_id}" if call_id else None)

            # Nếu đang trong cuộc gọi khác (đang rung hoặc đang call) -> auto từ chối (User Busy)
            # Không hiện popup để tránh "call collision"
            if self.current_call_id:
                # Nếu là cùng callId (hiếm khi xảy ra) thì bỏ qua để tránh vòng lặp
                if call_id and self.current_call_id != call_id:
                    self.send_command({
                        'type': 'CALL_REJECT',
                        'callId': call_id,
                        'reason': 'busy'
                    })
                return

            if not call_id or not from_uid or not signal_path:
                return

            # Hỏi người dùng có nhận cuộc gọi không
            reply = QMessageBox.question(
                self,
                "Cuộc gọi đến",
                f"Bạn có cuộc gọi video từ người dùng UID={from_uid}. Chấp nhận?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                # Lưu state cuộc gọi
                self.current_call_id = call_id
                self.current_call_peer_uid = from_uid
                self.current_call_signal_path = signal_path
                self.current_call_is_caller = False

                # Gửi lệnh ACCEPT cho server
                self.send_command({'type': 'CALL_ACCEPT', 'callId': call_id})

                # Mở cửa sổ video với vai trò callee (người nghe)
                self._open_video_call_window(is_caller=False)
            else:
                # Từ chối cuộc gọi (không bận, chỉ do user nhấn No)
                self.send_command({'type': 'CALL_REJECT', 'callId': call_id})

        elif cmd_type == 'CALL_INVITE_SENT':
            # Phản hồi khi mình gửi lời mời
            if not data.get('ok'):
                error_msg = data.get('error', 'Không thể bắt đầu cuộc gọi')
                QMessageBox.warning(self, "Video Call", error_msg)
                # Reset state nếu có
                self._reset_video_call_state()
            else:
                # Lưu thông tin cuộc gọi (caller)
                self.current_call_id = data.get('callId')
                self.current_call_peer_uid = data.get('toUid')
                self.current_call_signal_path = data.get('signalPath')
                self.current_call_is_caller = True

                # Khởi tạo timer: nếu sau 30s không có phản hồi thì tự kết thúc
                if self._call_ringing_timer is None:
                    self._call_ringing_timer = QTimer(self)
                    self._call_ringing_timer.setSingleShot(True)
                    self._call_ringing_timer.timeout.connect(self._on_call_ringing_timeout)
                self._call_ringing_timer.start(30_000)  # 30 giây

        elif cmd_type == 'CALL_ACCEPTED':
            # Mình là caller và phía kia đã chấp nhận
            call_id = data.get('callId')
            peer_uid = data.get('peerUid')
            signal_path = data.get('signalPath')

            if not call_id or not signal_path:
                return

            # Lưu lại cho chắc chắn
            self.current_call_id = call_id
            self.current_call_peer_uid = peer_uid or self.current_call_peer_uid
            self.current_call_signal_path = signal_path
            self.current_call_is_caller = True

            # Dừng timer đổ chuông (nếu còn)
            if self._call_ringing_timer and self._call_ringing_timer.isActive():
                self._call_ringing_timer.stop()

            # Mở cửa sổ video với vai trò caller
            self._open_video_call_window(is_caller=True)

        elif cmd_type == 'CALL_ACCEPT_OK':
            # ACK cho callee, có thể dùng để log/debug
            pass

        elif cmd_type == 'CALL_REJECTED':
            # Phía kia từ chối cuộc gọi
            reason = (data.get('reason') or '').lower()
            if reason == 'busy':
                msg = "Người dùng đang bận trong cuộc gọi khác."
            else:
                msg = "Người dùng đã từ chối cuộc gọi."
            QMessageBox.information(self, "Video Call", msg)
            # Dừng timer đổ chuông (nếu còn)
            if self._call_ringing_timer and self._call_ringing_timer.isActive():
                self._call_ringing_timer.stop()
            self._reset_video_call_state()

        elif cmd_type == 'CALL_END_OK':
            # ACK khi mình gửi CALL_END, chỉ reset state
            if self._call_ringing_timer and self._call_ringing_timer.isActive():
                self._call_ringing_timer.stop()
            self._reset_video_call_state()

        elif cmd_type == 'CALL_ENDED':
            # Phía kia kết thúc cuộc gọi
            call_id = data.get('callId')
            if call_id and self.current_call_id == call_id:
                QMessageBox.information(self, "Video Call", "Cuộc gọi đã kết thúc.")
                # Đóng cửa sổ nếu đang mở
                if self.video_call_window is not None:
                    try:
                        self.video_call_window.close()
                    except Exception:
                        pass
                if self._call_ringing_timer and self._call_ringing_timer.isActive():
                    self._call_ringing_timer.stop()
                self._reset_video_call_state()

    # --- LOGIC UI ---

    def open_find_friend(self):
        if not self.find_friend_window:
            self.find_friend_window = FindFriendWindow(self)
        self.find_friend_window.show()

    def open_friend_requests(self):
        if not self.friend_requests_window:
            self.friend_requests_window = FriendRequestsWindow(self)
        self.friend_requests_window.show()
        # Load data
        self.send_command({'type': 'FRIEND_REQUESTS'})

    def open_create_group(self):
        if not self.create_group_window:
            self.create_group_window = CreateGroupWindow(self)
        # Cập nhật danh sách bạn bè hiện có (nếu có)
        self.create_group_window.update_friends_list(self.friends_list)
        # Load danh sách bạn bè mới nhất từ server
        self.send_command({'type': 'LIST_FRIENDS'})
        self.create_group_window.show()

    def populate_list(self, items_list, is_group):
        """Đổ dữ liệu (bạn bè hoặc nhóm) vào QListWidget."""
        self.contact_list.clear()
        self.current_selected_button = None
        
        # Đặt tên thuộc tính dựa trên loại danh sách
        uid_key = 'groupId' if is_group else 'uid'
        
        for item in items_list:
            # Nhóm: Dùng name, Bạn bè: Dùng displayName/email
            name = item.get('name') if is_group else (item.get('displayName') or item.get('email'))
            item_uid = item.get(uid_key)
            
            if not item_uid:
                print(f"[ERROR] Group data missing {uid_key}.")
                continue

            # Tạo Item Widget tùy chỉnh (Giữ nguyên logic của populate_friends)
            item_widget = QListWidgetItem(self.contact_list)
            item_widget.setSizeHint(QSize(200, 60))
            
            btn = QPushButton(name)
            # ... (Style và Cursor giữ nguyên) ...
            btn.setStyleSheet("""
                QPushButton { text-align: left; padding: 15px; border: none; font-size: 14px; }
                QPushButton:hover { background-color: #e0e0e0; }
            """)
            btn.setCursor(Qt.PointingHandCursor)
            
            # Gắn UID/GroupID vào nút
            btn.setProperty("target_id", item_uid)
            btn.setProperty("name", name)
            btn.setProperty("is_group", is_group)
            
            # Thay đổi logic khi click: gọi select_item
            btn.clicked.connect(lambda _, b=btn: self.select_item(b))
            
            self.contact_list.setItemWidget(item_widget, btn)
                    
    def select_item(self, btn):
        """Xử lý sự kiện khi nhấn vào một mục (bạn bè hoặc nhóm)."""
        # Reset style nút cũ
        if self.current_selected_button:
            self.current_selected_button.setStyleSheet("""
                QPushButton { text-align: left; padding: 15px; border: none; font-size: 14px; }
                QPushButton:hover { background-color: #e0e0e0; }
            """)
            
        # Highlight nút mới
        btn.setStyleSheet("""
            QPushButton { text-align: left; padding: 15px; border: none; font-size: 14px; background-color: #B3E5FC; }
        """)
        self.current_selected_button = btn
        
        target_id = btn.property("target_id")
        name = btn.property("name")
        is_group = btn.property("is_group")
        
        # Stop any playing voice message when switching chat
        if self.voice_player:
            self.voice_player.stop()
        
        self.current_chat_uid = target_id
        self.current_chat_is_group = is_group
        self.lbl_chat_name.setText(name)

        # Chỉ cho phép gọi video trong chat 1-1
        if is_group:
            self.btn_video_call.setEnabled(False)
        else:
            self.btn_video_call.setEnabled(True)

        if is_group:
            self.group_members_value_label.setText("Đang tải danh sách thành viên...")
            self.group_members_panel.show()
        else:
            self.group_members_panel.hide()
            self._current_group_members = []
        
        for i in reversed(range(self.message_layout.count())): 
            widget = self.message_layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        # Tải lịch sử chat
        if is_group:
            # Gửi lệnh tải lịch sử nhóm (tùy vào commands.py của bạn)
            self.send_command({'type': 'LOAD_GROUP_HISTORY', 'groupId': target_id, 'limit': 50})
        else:
            # Gửi lệnh tải lịch sử DM
            self.send_command({'type': 'LOAD_THREAD', 'peerUid': target_id, 'limit': 50})
        if is_group:
            self.send_command({'type': 'LIST_GROUP_MEMBERS', 'groupId': target_id})


    def send_message(self):
        text = self.msg_input.text().strip()
        
        # Kiểm tra nếu chưa chọn đối tượng chat hoặc tin nhắn rỗng
        if not text or not self.current_chat_uid:
            return
            
        # 1. XÁC ĐỊNH LỆNH GỬI
        if self.current_chat_is_group:
            # Gửi tin nhắn nhóm
            command = {
                'type': 'SEND_GROUP_MESSAGE',
                'groupId': self.current_chat_uid,
                'text': text,
                'clientMsgId': str(int(time.time()*1000))
            }
        else:
            # Gửi tin nhắn riêng (DM)
            command = {
                'type': 'SEND_DM',
                'toUid': self.current_chat_uid,
                'text': text,
                'clientMsgId': str(int(time.time()*1000))
            }

        # 2. Gửi lên server
        self.send_command(command)
        
        # 3. Hiển thị ngay lập tức (Optimistic UI)
        self.add_message_bubble(text, is_self=True)
        self.msg_input.clear()
        
        # 4. Cuộn xuống cuối
        QApplication.processEvents()
        self.message_area.verticalScrollBar().setValue(self.message_area.verticalScrollBar().maximum())

    def _update_group_members_panel(self, members: list[dict]):
        """Hiển thị danh sách thành viên nhóm ngay dưới header."""
        if not self.current_chat_is_group:
            self.group_members_panel.hide()
            return

        if not members:
            self.group_members_value_label.setText("Không tìm thấy thành viên nào.")
            self.group_members_panel.show()
            return

        display_names = []
        for member in members:
            display = member.get('displayName') or member.get('email') or member.get('uid')
            if not display:
                continue
            display_names.append(display)

        if not display_names:
            self.group_members_value_label.setText("Không tìm thấy thành viên nào.")
        else:
            self.group_members_value_label.setText(", ".join(display_names))
        self.group_members_panel.show()
    
    def _make_thread_id(self, uid_a: str, uid_b: str) -> str:
        """Tạo thread_id từ 2 UID (giống như server)"""
        if uid_a <= uid_b:
            return f"{uid_a}__{uid_b}"
        return f"{uid_b}__{uid_a}"
    
    def _send_file_chunked(self, file_path, file_name, client_msg_id, to_uid=None, group_id=None):
        """Gửi file theo chunks cho file lớn"""
        CHUNK_SIZE = 500 * 1024  # 500KB mỗi chunk (sau base64 sẽ ~667KB)
        
        try:
            file_size = os.path.getsize(file_path)
            
            # Gửi metadata trước
            if group_id:
                start_cmd = {
                    'type': 'SEND_FILE_START',
                    'groupId': group_id,
                    'fileName': file_name,
                    'fileSize': file_size,
                    'clientMsgId': client_msg_id
                }
            else:
                start_cmd = {
                    'type': 'SEND_FILE_START',
                    'toUid': to_uid,
                    'fileName': file_name,
                    'fileSize': file_size,
                    'clientMsgId': client_msg_id
                }
            self.send_command(start_cmd)
            
            # Gửi từng chunk
            chunk_index = 0
            with open(file_path, 'rb') as f:
                while True:
                    chunk_data = f.read(CHUNK_SIZE)
                    if not chunk_data:
                        break
                    
                    chunk_b64 = base64.b64encode(chunk_data).decode('utf-8')
                    chunk_cmd = {
                        'type': 'SEND_FILE_CHUNK',
                        'chunkIndex': chunk_index,
                        'chunkData': chunk_b64,
                        'clientMsgId': client_msg_id
                    }
                    self.send_command(chunk_cmd)
                    chunk_index += 1
                    
                    # Cập nhật progress
                    if self._upload_progress_dialog:
                        progress = min(100, int((f.tell() / file_size) * 100))
                        self._upload_progress_dialog.setMaximum(100)
                        self._upload_progress_dialog.setValue(progress)
                    QApplication.processEvents()  # Để UI không bị đơ
            
            # Gửi kết thúc
            end_cmd = {
                'type': 'SEND_FILE_END',
                'clientMsgId': client_msg_id
            }
            self.send_command(end_cmd)
            
        except Exception as e:
            print(f"[Upload] Error sending file chunks: {e}")
            QMessageBox.critical(self, "Lỗi", f"Không thể gửi file: {str(e)}")
    
    def upload_file(self):
        """Chọn file và upload trực tiếp lên Firebase Storage, sau đó gửi URL cho server."""
        if not self.current_chat_uid or not self.current_user_uid:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn người nhận trước khi gửi file")
            return
        
        # Chọn file
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file để gửi",
            "",
            "All Files (*.*);;Images (*.png *.jpg *.jpeg *.gif *.bmp);;Audio (*.mp3 *.wav *.ogg);;Documents (*.pdf *.doc *.docx *.txt);;Videos (*.mp4 *.avi *.mov)"
        )
        
        if not file_path:
            return
        
        # Lấy tên file
        file_name = os.path.basename(file_path)
        
        # Tạo client message ID
        client_msg_id = str(int(time.time()*1000))
        
        # Lưu thông tin upload
        self._uploading_file_name = file_name
        self._upload_client_msg_id = client_msg_id
        
        # Hiển thị loading dialog
        self._show_upload_progress(file_name)
        
        # Tính conversation_id
        if self.current_chat_is_group:
            conversation_id = self.current_chat_uid
        else:
            conversation_id = self._make_thread_id(self.current_user_uid, self.current_chat_uid)
        
        # Upload trực tiếp lên Firebase Storage
        try:
            if not upload_file_to_firebase_storage:
                raise RuntimeError("Upload module not available. Please ensure client_upload.py exists.")
            
            if self._upload_progress_dialog:
                self._upload_progress_dialog.setLabelText(f"Đang upload: {file_name}...")
                self._upload_progress_dialog.setValue(50)  # Indeterminate for now
            
            file_url, content_type = upload_file_to_firebase_storage(
                file_path, 
                conversation_id, 
                self.id_token
            )
            
            # Xác định file_type từ content_type
            file_type = content_type.split("/")[0] if "/" in content_type else "application"
            
            if self._upload_progress_dialog:
                self._upload_progress_dialog.setValue(90)
            
            # Gửi URL cho server (không gửi file content)
            if self.current_chat_is_group:
                command = {
                    'type': 'SEND_FILE_URL',
                    'groupId': self.current_chat_uid,
                    'fileName': file_name,
                    'fileURL': file_url,
                    'fileType': file_type,
                    'clientMsgId': client_msg_id
                }
            else:
                command = {
                    'type': 'SEND_FILE_URL',
                    'toUid': self.current_chat_uid,
                    'fileName': file_name,
                    'fileURL': file_url,
                    'fileType': file_type,
                    'clientMsgId': client_msg_id
                }
            
            self.send_command(command)
            
            if self._upload_progress_dialog:
                self._upload_progress_dialog.setValue(100)
            
        except Exception as e:
            print(f"[Upload] Error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Lỗi", f"Không thể upload file: {str(e)}")
            self._hide_upload_progress()
        
    def add_message_bubble(self, text, is_self):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 5)
        
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setFont(QFont("Arial", 12))
        lbl.setContentsMargins(10, 10, 10, 10)
        lbl.setMaximumWidth(400)
        
        if is_self:
            layout.addStretch()
            lbl.setStyleSheet("background-color: #DCF8C6; border-radius: 10px; color: black;")
            layout.addWidget(lbl)
        else:
            lbl.setStyleSheet("background-color: white; border-radius: 10px; border: 1px solid #ddd; color: black;")
            layout.addWidget(lbl)
            layout.addStretch()
            
        self.message_layout.addWidget(container)
        # Scroll xuống dưới cùng
        QApplication.processEvents()
        self.message_area.verticalScrollBar().setValue(self.message_area.verticalScrollBar().maximum())
    
    def add_file_message(self, msg_data, is_self):
        """
        Hiển thị message có file (ảnh, audio, file).
        
        Args:
            msg_data: Dictionary chứa thông tin message:
                - fileType: "image", "audio", "video", "application"
                - fileURL: URL của file
                - fileName: Tên file
            is_self: True nếu là tin nhắn của mình
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 5)
        
        file_type = msg_data.get("fileType", "").lower()
        file_url = msg_data.get("fileURL", "")
        file_name = msg_data.get("fileName", "Unknown")
        
        # Tạo widget tương ứng với loại file
        if file_type == "image":
            widget = create_image_widget(
                file_url,
                is_self,
                self._show_image_context_menu,
                self._download_image
            )
        elif file_type == "audio":
            # Tạo callback để xóa widget khi file không tồn tại
            def remove_widget_callback():
                self._remove_message_widget(container)
            
            widget = create_audio_widget(
                file_url,
                file_name,
                is_self,
                self.voice_player.toggle_play_pause,
                self._download_voice,
                self.voice_player.seek,
                remove_widget_callback
            )
        elif file_type in ["video", "application"]:
            widget = create_file_widget(
                file_url,
                file_name,
                is_self,
                self._download_file
            )
        else:
            # Fallback: hiển thị như file thông thường
            widget = create_file_widget(
                file_url,
                file_name,
                is_self,
                self._download_file
            )
        
        if is_self:
            layout.addStretch()
            layout.addWidget(widget)
        else:
            layout.addWidget(widget)
            layout.addStretch()
        
        # Lưu container reference vào widget để có thể xóa sau này
        widget.setProperty('container', container)
        container.setProperty('file_url', file_url)
        container.setProperty('file_type', file_type)
        container.setProperty('file_name', file_name)
        
        self.message_layout.addWidget(container)
        QApplication.processEvents()
        self.message_area.verticalScrollBar().setValue(self.message_area.verticalScrollBar().maximum())
        
        # Kiểm tra file có tồn tại không (async)
        self._check_file_exists(file_url, container)
    
    def _check_file_exists(self, file_url, container):
        """Kiểm tra file có tồn tại trên Firebase Storage không."""
        # Kiểm tra cache trước
        if file_url in self._file_check_cache:
            exists = self._file_check_cache[file_url]
            if not exists:
                # File đã được kiểm tra và không tồn tại - xóa widget ngay
                print(f"[FileCheck] File không tồn tại (từ cache), đã xóa widget: {file_url}")
                self._remove_message_widget(container)
            # Nếu file tồn tại, giữ widget
            return
        
        def on_check_complete(checked_container, exists, checked_url):
            """Callback khi kiểm tra xong."""
            try:
                # Lưu kết quả vào cache
                self._file_check_cache[checked_url] = exists
                
                # Kiểm tra container có còn tồn tại không (tránh lỗi khi widget đã bị xóa)
                if not checked_container:
                    return
                
                # Kiểm tra container có còn trong UI không
                try:
                    parent = checked_container.parent()
                    if not parent:
                        return
                except RuntimeError:
                    # Widget đã bị xóa, bỏ qua
                    return
                
                if not exists:
                    # File không tồn tại - xóa widget
                    print(f"[FileCheck] File không tồn tại")
                    self._remove_message_widget(checked_container)
            except Exception as e:
                # Bỏ qua mọi lỗi để tránh crash
                print(f"[FileCheck] Error in callback: {e}")
        
        # Tạo worker thread và kết nối signal
        worker = FileCheckWorker(file_url, container)
        worker.check_complete.connect(on_check_complete)
        worker.finished.connect(worker.deleteLater)  # Tự xóa worker khi xong
        
        # Lưu worker để tránh bị garbage collect
        self._file_check_workers.append(worker)
        worker.finished.connect(lambda: self._file_check_workers.remove(worker) if worker in self._file_check_workers else None)
        
        # Bắt đầu kiểm tra
        worker.start()
    
    def _remove_message_widget(self, container):
        """Xóa message widget khỏi UI."""
        try:
            if not container:
                return
            
            # Kiểm tra container có còn tồn tại không
            try:
                parent = container.parent()
                if not parent:
                    return
            except RuntimeError:
                # Widget đã bị xóa, bỏ qua
                return
            
            # Tìm container trong layout
            for i in range(self.message_layout.count()):
                try:
                    item = self.message_layout.itemAt(i)
                    if item and item.widget() == container:
                        # Xóa widget khỏi layout
                        self.message_layout.removeWidget(container)
                        container.setParent(None)
                        container.deleteLater()
                        break
                except RuntimeError:
                    # Widget đã bị xóa trong lúc xử lý, bỏ qua
                    continue
        except Exception as e:
            # Bỏ qua mọi lỗi để tránh crash
            print(f"[RemoveWidget] Error removing widget: {e}")
    
    def _show_image_context_menu(self, image_url, file_name, position):
        """Hiển thị menu context cho ảnh (click chuột phải)."""
        menu = QMenu(self)
        
        # Action tải ảnh
        download_action = menu.addAction("Tải ảnh xuống")
        download_action.triggered.connect(lambda: self._download_image(image_url, file_name))
        
        # Action mở ảnh trong trình duyệt
        open_action = menu.addAction("🔗 Mở trong trình duyệt")
        open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(image_url)))
        
        # Hiển thị menu
        menu.exec_(position)
    
    def _download_image(self, image_url, file_name):
        """Tải ảnh xuống."""
        try:
            # Lấy extension từ tên file hoặc URL
            if not file_name:
                try:
                    from urllib.parse import urlparse, unquote
                    parsed_url = urlparse(image_url)
                    file_name = unquote(os.path.basename(parsed_url.path))
                    if not file_name or '.' not in file_name:
                        file_name = f"image_{int(time.time())}.jpg"
                except Exception:
                    file_name = f"image_{int(time.time())}.jpg"
            
            # Hỏi người dùng chọn nơi lưu ảnh
            # Lấy extension để filter
            ext = os.path.splitext(file_name)[1] if '.' in file_name else '.jpg'
            filter_text = f"Images (*{ext});;All Files (*.*)"
            
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Lưu ảnh",
                file_name,
                filter_text
            )
            
            if not save_path:
                return
            
            # Đảm bảo có extension
            if not os.path.splitext(save_path)[1]:
                save_path += ext
            
            # Tải ảnh
            response = requests.get(image_url, timeout=30, stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                QMessageBox.information(self, "Thành công", f"Đã tải ảnh: {os.path.basename(save_path)}")
            else:
                QMessageBox.warning(self, "Lỗi", f"Không thể tải ảnh. Status code: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Lỗi khi tải ảnh: {str(e)}")
            # Fallback: mở URL trong trình duyệt
            try:
                QDesktopServices.openUrl(QUrl(image_url))
            except Exception:
                pass
    
    
    def _show_upload_progress(self, file_name):
        """Hiển thị progress dialog khi upload file."""
        try:
            # Đóng dialog cũ nếu có
            self._hide_upload_progress()
            
            # Tạo progress dialog mới
            self._upload_progress_dialog = QProgressDialog(
                f"Đang tải lên: {file_name}...",
                "Hủy",  # Cancel button text
                0, 0,  # min, max (0,0 = indeterminate)
                self
            )
            self._upload_progress_dialog.setWindowTitle("Đang tải lên file")
            self._upload_progress_dialog.setWindowModality(Qt.WindowModal)
            self._upload_progress_dialog.setAutoClose(False)
            self._upload_progress_dialog.setAutoReset(False)
            self._upload_progress_dialog.setMinimumDuration(0)  # Hiển thị ngay lập tức
            self._upload_progress_dialog.setValue(0)  # Indeterminate mode
            self._upload_progress_dialog.show()
            
            # Kết nối cancel button (tùy chọn - có thể không hủy được nếu đã gửi lên server)
            # self._upload_progress_dialog.canceled.connect(self._cancel_upload)
            
        except Exception as e:
            print(f"[Upload] Error showing progress: {e}")
    
    def _hide_upload_progress(self):
        """Ẩn progress dialog khi upload xong."""
        try:
            if self._upload_progress_dialog:
                self._upload_progress_dialog.close()
                self._upload_progress_dialog.deleteLater()
                self._upload_progress_dialog = None
            
            # Reset upload info
            self._uploading_file_name = None
            self._upload_client_msg_id = None
        except Exception as e:
            print(f"[Upload] Error hiding progress: {e}")
    
    def _download_voice(self, audio_url, file_name):
        """Tải voice message xuống."""
        try:
            # Lấy extension từ tên file hoặc URL
            if not file_name:
                try:
                    from urllib.parse import urlparse, unquote
                    parsed_url = urlparse(audio_url)
                    file_name = unquote(os.path.basename(parsed_url.path))
                    if not file_name or '.' not in file_name:
                        file_name = f"voice_{int(time.time())}.wav"
                except Exception:
                    file_name = f"voice_{int(time.time())}.wav"
            
            # Hỏi người dùng chọn nơi lưu file
            ext = os.path.splitext(file_name)[1] if '.' in file_name else '.wav'
            filter_text = f"Audio Files (*{ext} *.mp3 *.wav *.ogg);;All Files (*.*)"
            
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Lưu voice message",
                file_name,
                filter_text
            )
            
            if not save_path:
                return
            
            # Đảm bảo có extension
            if not os.path.splitext(save_path)[1]:
                save_path += ext
            
            # Tải file
            response = requests.get(audio_url, timeout=30, stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                QMessageBox.information(self, "Thành công", f"Đã tải voice: {os.path.basename(save_path)}")
            else:
                QMessageBox.warning(self, "Lỗi", f"Không thể tải voice. Status code: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Lỗi khi tải voice: {str(e)}")
            # Fallback: mở URL trong trình duyệt
            try:
                QDesktopServices.openUrl(QUrl(audio_url))
            except Exception:
                pass
    
    def _download_file(self, file_url, file_name):
        """Tải file xuống."""
        try:
            # Hỏi người dùng chọn nơi lưu file
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Lưu file",
                file_name,
                "All Files (*.*)"
            )
            
            if not save_path:
                return
            
            # Tải file
            response = requests.get(file_url, timeout=30, stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                QMessageBox.information(self, "Thành công", f"Đã tải file: {file_name}")
            else:
                QMessageBox.warning(self, "Lỗi", f"Không thể tải file. Status code: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Lỗi khi tải file: {str(e)}")
            # Fallback: mở URL trong trình duyệt
            try:
                QDesktopServices.openUrl(QUrl(file_url))
            except Exception:
                pass

    def toggle_emoji_picker(self):
        """Hiện/ẩn emoji picker"""
        if self.emoji_picker.isVisible():
            self.emoji_picker.hide_picker()
        else:
            self.emoji_picker.show_picker()

    def insert_emoji(self, emoji):
        """Chèn emoji vào ô nhập tin nhắn"""
        current_text = self.msg_input.text()
        self.msg_input.setText(current_text + emoji)
        self.msg_input.setFocus()
        # Tùy chọn: ẩn emoji picker sau khi chọn
        # self.emoji_picker.hide_picker()

    def send_accept_request(self, uid):
        self.send_command({'type': 'ACCEPT_REQUEST', 'fromUid': uid})

    def send_reject_request(self, uid):
        self.send_command({'type': 'REJECT_REQUEST', 'fromUid': uid})
    
    def start_recording(self):
        """Bắt đầu ghi âm."""
        if not PYAUDIO_AVAILABLE:
            QMessageBox.warning(self, "Lỗi", "PyAudio chưa được cài đặt. Vui lòng cài với: pip install pyaudio")
            self.btn_voice.setChecked(False)
            return
        
        if not self.current_chat_uid:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn người nhận trước khi ghi âm")
            self.btn_voice.setChecked(False)
            return
        
        try:
            # Tạo file tạm để lưu audio
            temp_dir = tempfile.gettempdir()
            self.recording_file = os.path.join(temp_dir, f"voice_{int(time.time() * 1000)}.wav")
            
            # Khởi tạo audio recorder
            if not self.audio_recorder:
                self.audio_recorder = AudioRecorder(filename=self.recording_file)
            else:
                self.audio_recorder.filename = self.recording_file
            
            # Bắt đầu ghi âm
            self.audio_recorder.start_recording()
            self.is_recording = True
            self.recording_duration = 0
            
            # Hiển thị label và timer
            self.recording_label.setText("🔴 Đang ghi âm... 0s")
            self.recording_label.show()
            
            # Timer để cập nhật thời gian ghi âm
            if not self.recording_timer:
                self.recording_timer = QTimer()
                self.recording_timer.timeout.connect(self.update_recording_time)
            self.recording_timer.start(1000)  # Update mỗi giây
            
            # Đổi màu button
            self.btn_voice.setStyleSheet("""
                QPushButton { 
                    border: 2px solid #f44336; 
                    border-radius: 5px; 
                    background-color: #ffebee; 
                } 
                QPushButton:hover { 
                    background-color: #ffcdd2; 
                }
            """)
            
        except Exception as e:
            print(f"[Voice] Error starting recording: {e}")
            QMessageBox.warning(self, "Lỗi", f"Không thể bắt đầu ghi âm: {str(e)}")
            self.btn_voice.setChecked(False)
            self.is_recording = False
            if self.audio_recorder:
                try:
                    self.audio_recorder.cleanup()
                except Exception:
                    pass
    
    def update_recording_time(self):
        """Cập nhật thời gian ghi âm."""
        if self.is_recording:
            self.recording_duration += 1
            minutes = self.recording_duration // 60
            seconds = self.recording_duration % 60
            self.recording_label.setText(f"🔴 Đang ghi âm... {minutes}:{seconds:02d}")
    
    def stop_recording(self):
        """Dừng ghi âm và gửi file."""
        if not self.is_recording:
            return
        
        try:
            # Dừng timer
            if self.recording_timer:
                self.recording_timer.stop()
            
            self.is_recording = False
            self.recording_label.hide()
            
            # Reset button style
            self.btn_voice.setStyleSheet("""
                QPushButton { 
                    border: 1px solid #ddd; 
                    border-radius: 5px; 
                    background-color: white; 
                } 
                QPushButton:hover { 
                    background-color: #f0f0f0; 
                    border: 1px solid #2196F3; 
                }
                QPushButton:pressed {
                    background-color: #ffebee;
                    border: 1px solid #f44336;
                }
            """)
            self.btn_voice.setChecked(False)
            
            # Dừng ghi âm và lưu file
            file_path = None
            if self.audio_recorder:
                try:
                    file_path = self.audio_recorder.stop_recording()
                except Exception as e:
                    print(f"[Voice] Error stopping recorder: {e}")
            
            # Kiểm tra file có tồn tại và có kích thước > 0
            if file_path and os.path.isfile(file_path) and not self.current_chat_uid:
                QMessageBox.warning(self, "Thông báo", "Vui lòng chọn người nhận trước khi gửi voice")
                self._cleanup_recording_file()
                return
            
            if file_path and os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                # Kiểm tra độ dài tối thiểu (>= 0.5 giây) đã được kiểm tra trong AudioRecorder
                # Nếu file_path không None, nghĩa là đã pass kiểm tra độ dài trong AudioRecorder
                if file_size > 0:
                    # Lấy tên file
                    file_name = os.path.basename(file_path)
                    
                    # Tạo client message ID
                    client_msg_id = str(int(time.time()*1000))
                    
                    # Lưu thông tin upload
                    self._uploading_file_name = file_name
                    self._upload_client_msg_id = client_msg_id
                    
                    # Hiển thị loading dialog
                    self._show_upload_progress(file_name)
                    
                    # Tính conversation_id
                    if self.current_chat_is_group:
                        conversation_id = self.current_chat_uid
                    else:
                        if not self.current_user_uid:
                            QMessageBox.warning(self, "Thông báo", "Chưa có thông tin người dùng. Vui lòng thử lại.")
                            self._cleanup_recording_file()
                            return
                        conversation_id = self._make_thread_id(self.current_user_uid, self.current_chat_uid)
                    
                    # Upload trực tiếp lên Firebase Storage
                    try:
                        if not upload_file_to_firebase_storage:
                            raise RuntimeError("Upload module not available.")
                        
                        if self._upload_progress_dialog:
                            self._upload_progress_dialog.setLabelText(f"Đang upload voice: {file_name}...")
                            self._upload_progress_dialog.setValue(50)
                        
                        file_url, content_type = upload_file_to_firebase_storage(
                            file_path, 
                            conversation_id, 
                            self.id_token
                        )
                        
                        # Voice file type
                        file_type = "audio"
                        
                        if self._upload_progress_dialog:
                            self._upload_progress_dialog.setValue(90)
                        
                        # Gửi URL cho server
                        if self.current_chat_is_group:
                            command = {
                                'type': 'SEND_FILE_URL',
                                'groupId': self.current_chat_uid,
                                'fileName': file_name,
                                'fileURL': file_url,
                                'fileType': file_type,
                                'clientMsgId': client_msg_id
                            }
                        else:
                            command = {
                                'type': 'SEND_FILE_URL',
                                'toUid': self.current_chat_uid,
                                'fileName': file_name,
                                'fileURL': file_url,
                                'fileType': file_type,
                                'clientMsgId': client_msg_id
                            }
                        
                        self.send_command(command)
                        
                        if self._upload_progress_dialog:
                            self._upload_progress_dialog.setValue(100)
                        
                        self.recording_file = file_path
                        # Xóa file tạm sau 5 giây
                        QTimer.singleShot(5000, lambda: self._cleanup_recording_file())
                        
                    except Exception as e:
                        print(f"[Voice Upload] Error: {e}")
                        import traceback
                        traceback.print_exc()
                        QMessageBox.critical(self, "Lỗi", f"Không thể upload voice: {str(e)}")
                        self._hide_upload_progress()
                        self._cleanup_recording_file()
                    self.recording_file = file_path
                    
                    # Xóa file tạm sau 5 giây (để đảm bảo upload thành công)
                    QTimer.singleShot(5000, lambda: self._cleanup_recording_file())
                else:
                    QMessageBox.warning(self, "Thông báo", "Không có âm thanh được ghi lại. Vui lòng thử lại.")
                    self._cleanup_recording_file()
            else:
                if file_path is None:
                    # File không được tạo do quá ngắn (< 0.5 giây)
                    # AudioRecorder đã kiểm tra và không tạo file
                    QMessageBox.warning(self, "Thông báo", "Tin nhắn thoại quá ngắn (tối thiểu 0.5 giây). Vui lòng thử lại.")
                else:
                    QMessageBox.warning(self, "Lỗi", "Không tìm thấy file ghi âm")
                
        except Exception as e:
            print(f"[Voice] Error stopping recording: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Lỗi", f"Lỗi khi dừng ghi âm: {str(e)}")
            self.is_recording = False
            self.recording_label.hide()
            self.btn_voice.setChecked(False)
    
    def _cleanup_recording_file(self):
        """Xóa file ghi âm tạm."""
        try:
            if hasattr(self, 'recording_file') and self.recording_file and os.path.isfile(self.recording_file):
                os.remove(self.recording_file)
                print(f"[Voice] Đã xóa file tạm: {self.recording_file}")
                self.recording_file = None
        except Exception as e:
            print(f"[Voice] Error cleaning up recording file: {e}")
        
        # Cleanup audio recorder
        if self.audio_recorder:
            try:
                self.audio_recorder.cleanup()
            except Exception:
                pass

    def load_users(self):
        """Chuyển sang tab Người dùng và tải danh sách bạn bè."""
        self.set_tab_style(is_user_tab=True)
        self.send_command({'type': 'LIST_FRIENDS'})

    def load_groups(self):
        """Chuyển sang tab Nhóm và tải danh sách nhóm."""
        self.set_tab_style(is_user_tab=False)
        self.send_command({'type': 'LIST_GROUPS'}) # <--- LỆNH MỚI
    
    def leave_group(self):
        """Rời khỏi nhóm hiện tại."""
        if not self.current_chat_is_group or not self.current_chat_uid:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Thông báo", "Bạn không đang ở trong nhóm nào.")
            return
        
        # Xác nhận trước khi rời nhóm
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Xác nhận",
            "Bạn có chắc chắn muốn rời nhóm này?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Gửi lệnh rời nhóm
            self.send_command({
                'type': 'LEAVE_GROUP',
                'groupId': self.current_chat_uid
            })
            print(f"[Group] Đang gửi lệnh rời nhóm: {self.current_chat_uid}")

    def set_tab_style(self, is_user_tab):
        """Đổi style của nút tab khi được nhấn."""
        if is_user_tab:
            self.btn_tab_user.setStyleSheet("background-color: #00BFFF; color: white; border: none;")
            self.btn_tab_group.setStyleSheet("background-color: #f0f0f0; color: black; border: none;")
        else:
            self.btn_tab_user.setStyleSheet("background-color: #f0f0f0; color: black; border: none;")
            self.btn_tab_group.setStyleSheet("background-color: #00BFFF; color: white; border: none;")

    # ------------------------------------------------------------------
    # VIDEO CALL – CLIENT ACTIONS
    # ----------------------------
    def start_video_call(self):
        """Handler khi nhấn nút '📹 Video' – gửi CALL_INVITE cho người đang chat."""
        # Chỉ hỗ trợ chat 1-1, không hỗ trợ nhóm
        if self.current_chat_is_group or not self.current_chat_uid:
            QMessageBox.information(self, "Video Call", "Vui lòng chọn một người dùng (không phải nhóm) để gọi video.")
            return

        # Không cho phép bắt đầu cuộc gọi mới nếu đang trong một callId khác
        if self.current_call_id is not None:
            QMessageBox.warning(self, "Video Call", "Bạn đang trong một cuộc gọi khác. Hãy kết thúc trước khi gọi mới.")
            return

        # Gửi lệnh CALL_INVITE lên server
        payload = {
            "type": "CALL_INVITE",
            "toUid": self.current_chat_uid,
        }
        self.send_command(payload)

    # ------------------
    # VIDEO CALL HELPERS
    # ------------------
    def _reset_video_call_state(self):
        """Đặt lại state cuộc gọi video và giải phóng cửa sổ nếu cần."""
        # Dừng timer đổ chuông nếu còn chạy
        if self._call_ringing_timer and self._call_ringing_timer.isActive():
            self._call_ringing_timer.stop()
        self.current_call_id = None
        self.current_call_signal_path = None
        self.current_call_peer_uid = None
        self.current_call_is_caller = False
        # Không đóng cửa sổ ở đây (đã đóng ở nơi gọi), chỉ clear tham chiếu
        self.video_call_window = None

    def _open_video_call_window(self, is_caller: bool):
        """
        Tạo và hiển thị cửa sổ VideoCallWindow nếu VideoCallWindow khả dụng
        và có đủ thông tin cuộc gọi.
        """
        if VideoCallWindow is None:
            QMessageBox.warning(self, "Video Call", "Module VideoCallWindow chưa sẵn sàng.")
            return

        if not self.current_call_id or not self.current_call_signal_path:
            QMessageBox.warning(self, "Video Call", "Thiếu thông tin cuộc gọi (callId hoặc signalPath).")
            return

        # Lấy uid của chính mình: ưu tiên current_user_uid (UID), fallback về email
        my_uid = self.current_user_uid or self.current_user_email or "me"
        peer_uid = self.current_call_peer_uid or "peer"

        # Đóng cửa sổ cũ nếu còn
        if self.video_call_window is not None:
            try:
                self.video_call_window.close()
            except Exception:
                pass

        # Tạo cửa sổ video call
        self.video_call_window = VideoCallWindow(
            call_id=self.current_call_id,
            signal_path=self.current_call_signal_path,
            my_uid=my_uid,
            peer_uid=peer_uid,
            is_caller=is_caller
        )

        # Khi cửa sổ tự đóng, gửi CALL_END (nếu mình vẫn còn state cuộc gọi)
        def on_call_ended():
            if self.current_call_id:
                try:
                    self.send_command({'type': 'CALL_END', 'callId': self.current_call_id})
                except Exception:
                    pass
            self._reset_video_call_state()

        try:
            self.video_call_window.call_ended_signal.connect(on_call_ended)
        except Exception:
            pass

        self.video_call_window.show()

    def _on_call_ringing_timeout(self):
        """
        Được gọi phía caller khi hết 30s mà không có CALL_ACCEPTED / CALL_REJECTED.
        Tự gửi CALL_END và thông báo 'Không ai bắt máy'.
        """
        if not self.current_call_id:
            return
        try:
            # Gửi yêu cầu kết thúc cuộc gọi
            self.send_command({'type': 'CALL_END', 'callId': self.current_call_id})
        except Exception:
            pass

        QMessageBox.information(self, "Video Call", "Không ai bắt máy.")
        self._reset_video_call_state()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    print("Vui lòng chạy từ ui_login.py để có token xác thực.")
    window = ChatWindow()
    window.show()
    sys.exit(app.exec_())