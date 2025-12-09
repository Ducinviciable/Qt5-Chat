import cv2
import asyncio
import json
import requests
import sys
import os

from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer, pyqtSignal

from aiortc import RTCPeerConnection, RTCSessionDescription

# Handle import lib.firebase from both root and Client/ directory
try:
    from lib.firebase import FIREBASE_DATABASE_URL
except ImportError:
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from lib.firebase import FIREBASE_DATABASE_URL


class VideoCallWindow(QWidget):
    call_ended_signal = pyqtSignal()

    def __init__(self, call_id: str, signal_path: str, my_uid: str, peer_uid: str, is_caller: bool = False):
        """
            call_id: ID cuộc gọi (server tạo ra)
            signal_path: Path trên Firebase, ví dụ "/webrtc_calls/<callId>"
            my_uid: UID của chính mình
            peer_uid: UID của người bên kia
            is_caller: True nếu mình là người gọi, False nếu mình là người nhận
        """
        super().__init__()

        self.call_id = call_id
        self.signal_path = signal_path.rstrip("/") 
        self.my_uid = my_uid
        self.peer_uid = peer_uid
        self.is_caller = is_caller

        # Kết nối WebRTC
        self.pc = RTCPeerConnection()
        self.running = True

        # Camera local để hiển thị preview
        self.cap = cv2.VideoCapture(0)

        self._setup_ui()

        # Timer update khung hình local (preview)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_local_frame)
        self.timer.start(33)  # ~30fps

    def _setup_ui(self):
        self.setWindowTitle(f"Video Call - {self.my_uid[:6]} ↔ {self.peer_uid[:6]}")
        self.resize(900, 600)

        layout = QHBoxLayout()

        self.remote_label = QLabel("Đang thiết lập kết nối...")
        self.remote_label.setFixedSize(640, 480)
        self.remote_label.setStyleSheet("background: black; color: white;")

        self.local_label = QLabel("Me")
        self.local_label.setFixedSize(200, 150)
        self.local_label.setStyleSheet("border: 1px solid #4CAF50;")

        layout.addWidget(self.remote_label)
        layout.addWidget(self.local_label)

        self.setLayout(layout)

    def _update_local_frame(self):
        """Hiển thị preview từ webcam lên ô local."""
        if not self.running:
            return
        if not self.cap.isOpened():
            return
        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        img = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888)
        self.local_label.setPixmap(QPixmap.fromImage(img).scaled(
            self.local_label.width(),
            self.local_label.height()
        ))

    async def start_connection(self):
        try:
            if self.is_caller:
                await self._do_caller_flow()
            else:
                await self._do_callee_flow()
        except Exception as e:
            print(f"[VideoCall] start_connection error: {e}")
            self.remote_label.setText("Lỗi khi thiết lập cuộc gọi")

    async def _do_caller_flow(self):
        """Luồng dành cho người gọi: tạo Offer -> gửi -> chờ Answer."""
        # Tạo Offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        offer_payload = {
            "sdp": self.pc.localDescription.sdp,
            "type": "offer",
            "from": self.my_uid,
            "to": self.peer_uid,
        }

        # Ghi Offer lên Firebase: /webrtc_calls/{callId}/offer.json
        offer_url = f"{FIREBASE_DATABASE_URL}{self.signal_path}/offer.json"
        print(f"[VideoCall] PUT Offer -> {offer_url}")
        requests.put(offer_url, data=json.dumps(offer_payload))

        self.remote_label.setText("Đã gửi lời mời, chờ người kia trả lời...")

        # Chờ Answer
        await self._wait_for_answer()

    async def _do_callee_flow(self):
        """Luồng dành cho người nghe: chờ Offer -> tạo Answer -> gửi."""
        offer_url = f"{FIREBASE_DATABASE_URL}{self.signal_path}/offer.json"
        print(f"[VideoCall] Chờ Offer tại {offer_url}")

        # Polling Firebase để lấy Offer
        while self.running:
            try:
                resp = requests.get(offer_url, timeout=5)
                if resp.status_code == 200 and resp.content:
                    data = resp.json()
                else:
                    data = None
            except Exception as e:
                print(f"[VideoCall] Lỗi GET Offer: {e}")
                data = None

            if data and data.get("type") == "offer":
                print("[VideoCall] Nhận Offer, đang tạo Answer...")
                remote_desc = RTCSessionDescription(
                    sdp=data.get("sdp", ""),
                    type="offer"
                )
                await self.pc.setRemoteDescription(remote_desc)

                # Tạo Answer
                answer = await self.pc.createAnswer()
                await self.pc.setLocalDescription(answer)

                answer_payload = {
                    "sdp": self.pc.localDescription.sdp,
                    "type": "answer",
                    "from": self.my_uid,
                    "to": self.peer_uid,
                }

                answer_url = f"{FIREBASE_DATABASE_URL}{self.signal_path}/answer.json"
                print(f"[VideoCall] PUT Answer -> {answer_url}")
                requests.put(answer_url, data=json.dumps(answer_payload))

                self.remote_label.setText("Đã trả lời cuộc gọi, chờ kết nối...")
                return

            await asyncio.sleep(1)

        self.remote_label.setText("Huỷ chờ Offer (cửa sổ đã đóng).")

    async def _wait_for_answer(self):
        """Caller: chờ Answer xuất hiện trên Firebase."""
        answer_url = f"{FIREBASE_DATABASE_URL}{self.signal_path}/answer.json"
        print(f"[VideoCall] Chờ Answer tại {answer_url}")

        while self.running:
            try:
                resp = requests.get(answer_url, timeout=5)
                if resp.status_code == 200 and resp.content:
                    data = resp.json()
                else:
                    data = None
            except Exception as e:
                print(f"[VideoCall] Lỗi GET Answer: {e}")
                data = None

            if data and data.get("type") == "answer":
                print("[VideoCall] Nhận Answer, hoàn tất SDP handshake.")
                answer = RTCSessionDescription(
                    sdp=data.get("sdp", ""),
                    type="answer"
                )
                await self.pc.setRemoteDescription(answer)
                self.remote_label.setText("Đã thiết lập kết nối (SDP OK).")
                return

            await asyncio.sleep(1)

        self.remote_label.setText("Huỷ chờ Answer (cửa sổ đã đóng).")

    def closeEvent(self, event):
        self.running = False

        # Dừng timer preview nếu còn chạy
        try:
            if hasattr(self, "timer") and self.timer is not None:
                self.timer.stop()
        except Exception as e:
            print(f"[VideoCall] Error stopping timer: {e}")

        # Giải phóng camera an toàn
        try:
            if getattr(self, "cap", None) is not None and self.cap.isOpened():
                self.cap.release()
        except Exception as e:
            print(f"[VideoCall] Error releasing camera: {e}")

        # Đóng peer connection
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # qasync / asyncio loop đang chạy: tạo task nền
                loop.create_task(self.pc.close())
            else:
                # Fallback: đóng đồng bộ
                loop.run_until_complete(self.pc.close())
        except Exception as e:
            print(f"[VideoCall] Error closing RTCPeerConnection: {e}")

        # Báo cho bên ngoài biết cuộc gọi kết thúc
        try:
            self.call_ended_signal.emit()
        except Exception as e:
            print(f"[VideoCall] Error emitting call_ended_signal: {e}")

        event.accept()