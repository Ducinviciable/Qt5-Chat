import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLineEdit, 
                             QPushButton, QLabel, QHBoxLayout, QSpacerItem, 
                             QSizePolicy, QStackedWidget, QFrame, QMessageBox)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QThread

# Import giao diện chat (đảm bảo bạn có file ui_chat.py cùng thư mục)
import ui_chat

# Import hàm đăng nhập từ file auth.py bạn vừa gửi
try:
    from auth import firebase_sign_in  #
except ImportError:
    # Fallback nếu chạy thử mà chưa setup đúng cấu trúc thư mục
    def firebase_sign_in(email, password):
        print("Lỗi: Không tìm thấy module auth.py")
        return None

# --- WORKER THREAD CHO ĐĂNG NHẬP ---
class LoginWorker(QThread):
    # Signal trả về: (thành công hay không, thông báo/token, email)
    login_finished = pyqtSignal(bool, str, str)

    def __init__(self, email, password):
        super().__init__()
        self.email = email
        self.password = password

    def run(self):
        try:
            # Gọi hàm đăng nhập từ auth.py
            token = firebase_sign_in(self.email, self.password)
            if token:
                self.login_finished.emit(True, token, self.email)
            else:
                self.login_finished.emit(False, "Sai email hoặc mật khẩu, hoặc lỗi kết nối.", "")
        except Exception as e:
            self.login_finished.emit(False, f"Lỗi hệ thống: {str(e)}", "")


# --- CẤU TRÚC CƠ BẢN ---
class BaseScreen(QWidget):
    change_screen = pyqtSignal(int) 

    def __init__(self, title):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignCenter)
        self.layout.setSpacing(20)
        self.layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.setup_header(title)
        
    def setup_header(self, title):
        icon_label = QLabel("💬")
        icon_label.setFont(QFont("Arial", 48))
        icon_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 18, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(title_label)

    def setup_footer(self, main_layout):
        main_layout.addSpacing(40) 
        link_widget = QWidget()
        link_layout = QVBoxLayout(link_widget)
        link_layout.setAlignment(Qt.AlignCenter)
        link_layout.setContentsMargins(0, 0, 0, 0)
        link_layout.setSpacing(10)

        no_account_layout = QHBoxLayout()
        no_account_layout.setAlignment(Qt.AlignCenter)
        no_account_label = QLabel("Chưa có tài khoản?")
        no_account_link = QLabel('<a href="#">Đăng ký</a>')
        no_account_link.setOpenExternalLinks(False)
        no_account_link.setTextFormat(Qt.RichText)
        no_account_link.setStyleSheet("QLabel { color: blue; text-decoration: underline; }") 
        no_account_link.linkActivated.connect(lambda: self.change_screen.emit(6)) # Index 6 là màn hình đăng ký
        
        no_account_layout.addWidget(no_account_label)
        no_account_layout.addWidget(no_account_link)
        link_layout.addLayout(no_account_layout)
        
        have_account_layout = QHBoxLayout()
        have_account_layout.setAlignment(Qt.AlignCenter)
        have_account_label = QLabel("Đã có tài khoản?")
        have_account_link = QLabel('<a href="#">Đăng nhập</a>')
        have_account_link.setOpenExternalLinks(False)
        have_account_link.setTextFormat(Qt.RichText)
        have_account_link.setStyleSheet("QLabel { color: blue; text-decoration: underline; }") 
        have_account_link.linkActivated.connect(lambda: self.change_screen.emit(0)) # Index 0 là màn hình đăng nhập

        have_account_layout.addWidget(have_account_label)
        have_account_layout.addWidget(have_account_link)
        link_layout.addLayout(have_account_layout)
        
        main_layout.addWidget(link_widget)
        main_layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

# --- MÀN HÌNH 0: ĐĂNG NHẬP ---
class LoginScreen(BaseScreen):
    # Signal gửi về MainWindow: host, port, token, email
    login_successful = pyqtSignal(str, int, str, str)

    def __init__(self):
        super().__init__("Đăng nhập")
        
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(50, 20, 50, 20) 
        
        # Host/Port settings (Ẩn hoặc hiện tùy nhu cầu, ở đây để hiện để dễ debug)
        settings_layout = QHBoxLayout()
        self.host_input = QLineEdit("localhost")
        self.host_input.setPlaceholderText("Host")
        self.port_input = QLineEdit("8080")
        self.port_input.setPlaceholderText("Port")
        self.port_input.setFixedWidth(60)
        settings_layout.addWidget(self.host_input)
        settings_layout.addWidget(self.port_input)
        form_layout.addLayout(settings_layout)

        # Email
        email_label = QLabel("Email")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("example@gmail.com")
        self.email_input.setFixedHeight(40)
        self.email_input.setStyleSheet("padding: 5px; border: 1px solid #ccc; border-radius: 5px;")
        
        # Mật khẩu
        password_label = QLabel("Mật khẩu")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password) 
        self.password_input.setFixedHeight(40)
        self.password_input.setStyleSheet("padding: 5px; border: 1px solid #ccc; border-radius: 5px;")
        
        # Nút Đăng nhập
        self.login_button = QPushButton("Đăng nhập")
        self.set_button_style(self.login_button)
        self.login_button.setFixedHeight(45)
        
        # Kết nối sự kiện
        self.login_button.clicked.connect(self.handle_login)
        self.password_input.returnPressed.connect(self.handle_login)

        form_layout.addWidget(email_label)
        form_layout.addWidget(self.email_input)
        form_layout.addSpacing(15)
        form_layout.addWidget(password_label)
        form_layout.addWidget(self.password_input)
        form_layout.addSpacing(30)
        form_layout.addWidget(self.login_button)
        
        self.layout.addWidget(form_widget)
        
        # Quên mật khẩu
        forgot_layout = QHBoxLayout()
        forgot_layout.setAlignment(Qt.AlignCenter)
        forgot_link = QLabel('<a href="#">Quên mật khẩu?</a>')
        forgot_link.setOpenExternalLinks(False)
        forgot_link.linkActivated.connect(lambda: self.change_screen.emit(1))
        forgot_layout.addWidget(forgot_link)
        self.layout.addLayout(forgot_layout)
        
        # Footer (Chưa có tài khoản...)
        self.setup_footer(self.layout)

    def set_button_style(self, button):
        button.setFont(QFont("Arial", 10, QFont.Bold))
        button.setStyleSheet("""
            QPushButton { background-color: #D3D3D3; color: black; border-radius: 20px; border: none; }
            QPushButton:hover { background-color: #2f32d6; }
            QPushButton:disabled { background-color: #EEEEEE; color: #AAAAAA; }
        """)

    def handle_login(self):
        email = self.email_input.text().strip()
        password = self.password_input.text().strip()
        
        if not email or not password:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập Email và Mật khẩu.")
            return

        # Disable nút để tránh bấm nhiều lần
        self.login_button.setEnabled(False)
        self.login_button.setText("Đang đăng nhập...")

        # Tạo worker thread
        self.worker = LoginWorker(email, password)
        self.worker.login_finished.connect(self.on_login_finished)
        self.worker.start()

    def on_login_finished(self, success, result, email):
        self.login_button.setEnabled(True)
        self.login_button.setText("Đăng nhập")
        
        if success:
            token = result
            host = self.host_input.text().strip()
            try:
                port = int(self.port_input.text().strip())
            except ValueError:
                port = 8080
            
            # Emit signal để MainWindow chuyển sang ChatWindow
            self.login_successful.emit(host, port, token, email)
        else:
            QMessageBox.critical(self, "Đăng nhập thất bại", result)


class SignUpScreen(BaseScreen):
    def __init__(self):
        super().__init__("Đăng ký")
        lbl = QLabel("Chức năng đăng ký đang phát triển.\nVui lòng dùng tài khoản có sẵn.")
        lbl.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(lbl)
        self.setup_footer(self.layout)

class ForgotPassSearchScreen(BaseScreen):
    def __init__(self):
        super().__init__("Quên mật khẩu")
        lbl = QLabel("Chức năng quên mật khẩu đang phát triển.")
        lbl.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(lbl)
        self.setup_footer(self.layout)

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chat App - Login")
        self.setGeometry(100, 100, 400, 650)
        self.main_layout = QVBoxLayout(self)
        
        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget)
        
        self.init_ui()

    def init_ui(self):
        # 0. Login
        self.login_screen = LoginScreen()
        self.stacked_widget.addWidget(self.login_screen)
        
        # 1. Forgot Password
        self.forgot_screen = ForgotPassSearchScreen()
        self.stacked_widget.addWidget(self.forgot_screen)
        
        # 6. Signup
        self.signup_screen = SignUpScreen()
        self.stacked_widget.addWidget(self.signup_screen) # Index sẽ tự động tăng, cần map đúng index nếu dùng hardcode

        # Map signals
        self.login_screen.change_screen.connect(self.switch_screen)
        self.forgot_screen.change_screen.connect(self.switch_screen)
        self.signup_screen.change_screen.connect(self.switch_screen)

        # Kết nối sự kiện đăng nhập thành công
        self.login_screen.login_successful.connect(self.handle_login_success)

    def switch_screen(self, index):
        if index == 6: # Signup request
            self.stacked_widget.setCurrentWidget(self.signup_screen)
        elif index == 1: # Forgot request
            self.stacked_widget.setCurrentWidget(self.forgot_screen)
        else:
            self.stacked_widget.setCurrentWidget(self.login_screen)

    def handle_login_success(self, host, port, id_token, email):
        print(f"Login OK: {email} -> Connecting to {host}:{port}")
        
        try:
            # Khởi tạo cửa sổ Chat
            self.chat_window = ui_chat.ChatWindow(host=host, port=port, id_token=id_token, user_email=email)
            self.chat_window.show()                
            # Đóng cửa sổ Login hiện tại
            self.close()
            
        except Exception as e:
            QMessageBox.critical(self, "Lỗi khởi tạo Chat", str(e))
            print(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())