# Ứng dụng Chat Real-time với PyQt5

Ứng dụng chat real-time được xây dựng bằng PyQt5 cho client và Python Socket Server, tích hợp Firebase Authentication, Firestore, và Google Cloud Storage để hỗ trợ chat nhắn tin, gửi file, ghi âm voice message.

## ✨ Tính năng chính

- 🔐 **Xác thực người dùng**: Đăng nhập/đăng ký với Firebase Authentication (email/password)
- 💬 **Chat real-time**: Nhắn tin cá nhân (DM) và nhóm với optimistic UI
- 👥 **Quản lý bạn bè**: Tìm kiếm, gửi/nhận lời mời kết bạn, quản lý danh sách bạn bè
- 👨‍👩‍👧‍👦 **Quản lý nhóm**: Tạo và tham gia nhóm chat
- 📁 **Gửi file**: Upload và chia sẻ hình ảnh, tài liệu (PDF, ZIP, DOC...)
- 🎤 **Voice message**: Ghi âm và gửi tin nhắn thoại với playback controls
- 😊 **Emoji picker**: Chọn và gửi emoji với nhiều danh mục
- 📥 **Download file**: Tải xuống hình ảnh, voice message, và các file đã gửi
- 📹 **Video call (beta)**: Gọi video 1–1 sử dụng WebRTC (aiortc) với signaling hybrid (TCP server + Firebase Realtime Database)

## 📁 Cấu trúc dự án

```
LTM-CK/
├── Client/                      # Ứng dụng client (PyQt5 GUI)
│   ├── main.py                  # Điểm khởi động client (Qt + asyncio qua qasync)
│   ├── ui_login.py              # Màn hình đăng nhập/đăng ký
│   ├── ui_chat.py               # Giao diện chat chính
│   ├── video_call_ui.py         # Cửa sổ video call dùng aiortc + Firebase signaling
│   ├── auth.py                  # Xác thực Firebase
│   ├── voice/                   # Module xử lý voice
│   │   ├── __init__.py
│   │   ├── recorder.py          # AudioRecorder class (ghi âm)
│   │   └── player.py            # VoicePlayer class (phát audio)
│   └── widgets/                 # UI components tái sử dụng
│       ├── __init__.py
│       ├── emoji_picker.py      # EmojiPicker widget
│       └── file_message_widgets.py  # Widgets hiển thị file/ảnh/audio
│
├── Server/                      # Socket server
│   ├── main.py                  # Khởi chạy server
│   ├── handler.py               # Xử lý kết nối client
│   ├── commands.py              # Logic xử lý các lệnh
│   ├── state.py                 # State management (clients, locks)
│   ├── firebase_admin_utils.py  # Firebase Admin SDK utilities
│   └── diagnostics_list_friends.py  # Script tiện ích debug
│
├── lib/                         # Thư viện dùng chung
│   ├── upload.py                # Upload file lên Google Cloud Storage
│   ├── firebase.py              # Firebase configuration
│   └── firebase-service.json    # Firebase service account credentials
│
├── requirements.txt             # Dependencies
└── README.md                    # Tài liệu này
```

## 🔧 Yêu cầu hệ thống

- Python 3.7+
- Firebase project với:
  - Authentication (Email/Password enabled)
  - Firestore Database
  - Google Cloud Storage (cho file upload)
- Service account key từ Firebase Console

## ⚙️ Chức năng

### 🖥️ Server (Trong dự án)

Server xử lý các lệnh từ client và tương tác với Firebase:

- **Xác thực (AUTH)**: Xác thực ID token từ Firebase, ánh xạ socket ↔ uid
- **Quản lý bạn bè**:
  - `FIND_USER`: Tìm kiếm người dùng theo email
  - `LIST_FRIENDS`: Liệt kê danh sách bạn bè
  - `SEND_FRIEND_REQUEST`: Gửi lời mời kết bạn
  - `ACCEPT_REQUEST`: Chấp nhận lời mời kết bạn
  - `REJECT_REQUEST`: Từ chối lời mời kết bạn
  - `FRIEND_REQUESTS`: Lấy danh sách lời mời đang chờ
- **Chat cá nhân (DM)**:
  - `SEND_DM`: Gửi tin nhắn cá nhân (lưu vào Firebase Realtime Database)
  - `LOAD_THREAD`: Tải lịch sử chat cá nhân (Realtime DB + Firestore file messages)
- **Quản lý nhóm**:
  - `CREATE_GROUP`: Tạo nhóm chat mới
  - `LIST_GROUPS`: Liệt kê các nhóm đã tham gia
  - `SEND_GROUP_MESSAGE`: Gửi tin nhắn vào nhóm
  - `LOAD_GROUP_HISTORY`: Tải lịch sử nhóm (Realtime DB + Firestore file messages)
  - `LEAVE_GROUP`: Rời khỏi nhóm
  - `LIST_GROUP_MEMBERS`: Liệt kê thành viên trong nhóm
- **Gửi file**:
  - `SEND_FILE`: Upload file lên Google Cloud Storage, lưu metadata vào Firestore, gửi đến người nhận
- **Broadcast**: Gửi tin nhắn đến tất cả client đang kết nối
- **Connection Management**: Quản lý kết nối socket, xử lý disconnect, cleanup

### 🔥 Firebase Services

Server sử dụng các dịch vụ Firebase sau:

- **Firebase Authentication**:
  - Xác thực email/password
  - Verify ID token để lấy uid, email, displayName
  - Tạo user profile tự động khi đăng nhập lần đầu

- **Firestore Database**:
  - `users/{uid}` - Thông tin người dùng (email, displayName, createdAt)
  - `friends/{uid}/friends/{friendUid}` - Danh sách bạn bè
  - `friendRequests/{uid}/requests/{requestId}` - Lời mời kết bạn
  - `groups/{groupId}` - Thông tin nhóm (name, members, createdAt)
  - `conversations/{conversationId}/messages/{messageId}` - Metadata tin nhắn file (fileURL, fileType, fileName, senderId, timestamp)

- **Firebase Realtime Database**:
  - `threads/{threadId}/messages/{messageId}` - Tin nhắn text trong chat cá nhân
  - `groups/{groupId}/messages/{messageId}` - Tin nhắn text trong nhóm

- **Google Cloud Storage**:
  - Lưu trữ file upload (hình ảnh, audio, documents)
  - Tạo public URL cho file
  - Tổ chức theo đường dẫn: `chat_files/{conversationId}/{fileName}`

### 💻 Client

Ứng dụng PyQt5 cung cấp giao diện người dùng:

- **Xác thực**:
  - Đăng nhập với email/password
  - Đăng ký tài khoản mới
  - Quên mật khẩu (UI scaffold)
  - Kết nối socket và xác thực với server

- **Quản lý bạn bè**:
  - Tìm kiếm người dùng theo email
  - Gửi lời mời kết bạn
  - Xem danh sách lời mời đang chờ
  - Chấp nhận/từ chối lời mời
  - Hiển thị danh sách bạn bè

- **Chat cá nhân (DM)**:
  - Chọn bạn bè để chat
  - Gửi/nhận tin nhắn text real-time
  - Tải lịch sử chat khi mở conversation
  - Optimistic UI (hiển thị tin nhắn ngay khi gửi)
  - Scroll tự động đến tin nhắn mới

- **Quản lý nhóm**:
  - Tạo nhóm mới
  - Xem danh sách nhóm đã tham gia
  - Chọn nhóm để chat
  - Gửi/nhận tin nhắn trong nhóm
  - Tải lịch sử nhóm
  - Xem danh sách thành viên
  - Rời khỏi nhóm

- **Gửi file**:
  - Chọn file từ máy tính (ảnh, PDF, ZIP, DOC...)
  - Upload file với progress indicator
  - Hiển thị file đã gửi/nhận
  - **Hiển thị hình ảnh**: Tải và hiển thị ảnh inline với QPixmap
  - **Phát audio**: Widget với nút play/pause, progress slider, time label
  - **Download file**: Nút download cho tài liệu (PDF, ZIP, DOC...)

- **Voice message**:
  - Ghi âm tin nhắn thoại (bằng PyAudio)
  - Hiển thị thời gian ghi âm
  - Upload file audio lên server
  - Phát voice message với controls (play/pause, seek, time display)
  - Download voice message

- **Emoji picker**:
  - Chọn emoji từ nhiều danh mục (sử dụng qtawesome)
  - Chèn emoji vào ô nhập tin nhắn
  - Gửi emoji như text bình thường
- **Video call (beta)**:
  - Gọi video 1–1 giữa hai người dùng
  - Signaling Phase 1: dùng TCP server (`CALL_INVITE`, `CALL_ACCEPT`, `CALL_REJECT`, `CALL_END`)
  - Signaling Phase 2: dùng Firebase Realtime Database (`/webrtc_calls/{callId}/offer|answer`) với aiortc
  - Event loop hybrid Qt + asyncio thông qua `qasync` (xem `Client/main.py`)

- **UI/UX**:
  - Tab Friends/Groups để chuyển đổi giữa chat cá nhân và nhóm
  - Phân biệt tin nhắn của mình và người khác (màu sắc khác nhau)
  - Context menu cho hình ảnh (lưu ảnh)
  - Progress dialog khi upload file
  - Error handling và thông báo lỗi
  - Network worker thread (không làm đơ UI)

## 📦 Cài đặt

### 1. Clone repository và tạo virtual environment

```bash
# Tạo virtual environment
python -m venv .venv

# Kích hoạt virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Cài đặt dependencies
pip install -r requirements.txt
```

### 2. Cấu hình Firebase

1. Tải service account key từ Firebase Console:
   - Vào Project Settings → Service Accounts
   - Generate new private key
   - Lưu file JSON vào `lib/firebase-service.json`

2. Cấu hình Firebase Storage:
   - Tạo bucket trong Google Cloud Storage
   - Lấy bucket name (ví dụ: `your-project.appspot.com`)
   - Thêm vào `lib/firebase-service.json` hoặc biến môi trường:
     ```json
     {
       "storage_bucket": "your-project.appspot.com"
     }
     ```

3. (Tùy chọn) Tạo file `.env` ở root project:
   ```env
   FIREBASE_STORAGE_BUCKET=your-project.appspot.com
   ```

### 3. Cấu hình Firestore

Đảm bảo Firestore Database đã được tạo và có cấu trúc:
- `users/{uid}` - Thông tin người dùng
- `friends/{uid}/friends/{friendUid}` - Danh sách bạn bè
- `friendRequests/{uid}/requests/{requestId}` - Lời mời kết bạn
- `groups/{groupId}` - Thông tin nhóm
- `conversations/{conversationId}/messages/{messageId}` - Tin nhắn file

## 🚀 Chạy ứng dụng

### Chạy Server

```bash
# Từ thư mục root
python Server/main.py
```

Server sẽ lắng nghe trên `0.0.0.0:8080` (mặc định).

### Chạy Client

```bash
# Từ thư mục root
python Client/main.py
```

Ứng dụng GUI sẽ mở màn hình đăng nhập.

## 🏗️ Kiến trúc và luồng hoạt động

### 1. Xác thực người dùng

```
Client (ui_login.py)
    ↓
Firebase Auth API (auth.py)
    ↓
Nhận ID Token
    ↓
Kết nối Socket Server
    ↓
Server xác thực token (firebase_admin_utils.py)
    ↓
Ánh xạ socket ↔ uid
```

### 2. Gửi/Nhận tin nhắn

```
Client gửi: CMD {"type": "SEND_DM", "toUid": "...", "message": "..."}
    ↓
Server (commands.py) xử lý
    ↓
Lưu vào Firebase Realtime Database
    ↓
Broadcast đến người nhận (nếu online)
    ↓
Client nhận và hiển thị (optimistic UI)
```

### 3. Upload file

```
Client chọn file
    ↓
Upload lên Google Cloud Storage (lib/upload.py)
    ↓
Lưu metadata vào Firestore
    ↓
Server gửi FILE_MESSAGE đến người nhận
    ↓
Client hiển thị file (image/audio/document widget)
```

### 4. Voice message

```
Client bấm nút ghi âm
    ↓
AudioRecorder (voice/recorder.py) ghi âm bằng PyAudio
    ↓
Lưu file WAV tạm
    ↓
Upload lên Storage như file thông thường
    ↓
Người nhận phát bằng VoicePlayer (voice/player.py)
```

## 📚 Các module chính

### Client

| File | Mô tả |
|------|-------|
| `ui_chat.py` | Giao diện chat chính, quản lý state, xử lý commands (bao gồm video call signaling), render messages |
| `ui_login.py` | Màn hình đăng nhập/đăng ký, routing sang chat window |
| `video_call_ui.py` | `VideoCallWindow` – xử lý WebRTC (aiortc) + Firebase signaling cho video call |
| `auth.py` | Hàm `firebase_sign_in()` - xác thực với Firebase Auth |
| `voice/recorder.py` | `AudioRecorder` class - ghi âm bằng PyAudio |
| `voice/player.py` | `VoicePlayer` class - phát audio với QMediaPlayer |
| `widgets/emoji_picker.py` | `EmojiPicker` widget - chọn emoji |
| `widgets/file_message_widgets.py` | Widgets hiển thị image/audio/file messages |

### Server

| File | Mô tả |
|------|-------|
| `handler.py` | Xử lý kết nối socket, xác thực, parse commands, broadcast |
| `commands.py` | Logic nghiệp vụ cho tất cả commands (SEND_DM, LIST_FRIENDS, SEND_FILE...) |
| `firebase_admin_utils.py` | Xác thực ID token, tạo user profile, tương tác Firestore |
| `state.py` | Global state: `clients` dict, `clients_lock`, mapping uid ↔ socket |

### Lib

| File | Mô tả |
|------|-------|
| `upload.py` | `upload_file()` - upload lên GCS, `send_message_file()` - lưu metadata vào Firestore |
| `firebase.py` | Khởi tạo Firebase Admin SDK |

## 🔌 Protocol

Client và Server giao tiếp qua format:

```
CMD {json_command}
```

Ví dụ:
- `CMD {"type": "AUTH", "idToken": "..."}`
- `CMD {"type": "SEND_DM", "toUid": "abc123", "message": "Hello"}`
- `CMD {"type": "SEND_FILE", "filePath": "/path/to/file.jpg", "toUid": "abc123"}`

## 🛠️ Dependencies

- `firebase-admin` - Firebase Admin SDK
- `google-cloud-storage` - Google Cloud Storage client
- `PyQt5==5.15.9` - GUI framework
- `qtawesome` - Font Awesome icons cho PyQt5
- `python-dotenv` - Load environment variables
- `requests` - HTTP requests (download files)
- `pyaudio` - Audio recording (voice messages)

## 📝 Ghi chú

- **PyAudio trên Windows**: Có thể cần cài đặt thêm dependencies. Xem [PyAudio installation guide](https://people.csail.mit.edu/hubert/pyaudio/docs/).
- **Firebase Storage**: Đảm bảo bucket đã được tạo và có quyền truy cập phù hợp.
- **Network**: Server mặc định chạy trên port 8080. Có thể thay đổi trong `Server/main.py`.

## 🐛 Troubleshooting

### Lỗi "PyAudio not available"
```bash
# Windows
pip install pipwin
pipwin install pyaudio

# Linux
sudo apt-get install portaudio19-dev python3-pyaudio
pip install pyaudio

# macOS
brew install portaudio
pip install pyaudio
```

### Lỗi "Failed to initialize storage bucket"
- Kiểm tra `lib/firebase-service.json` có đúng format
- Đảm bảo `storage_bucket` đã được cấu hình
- Kiểm tra quyền service account có quyền truy cập Storage

### Lỗi "Cannot load friends/groups"
- Kiểm tra Firestore có dữ liệu
- Kiểm tra Firebase Admin SDK đã được khởi tạo đúng
- Xem logs trong `Server/commands.py` để debug

## 📄 License

License is free

---

**Phát triển bởi**: LTM-CK Team
