import os
import time

import qtawesome as qta
import requests
from PyQt5.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QSlider,
)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt, QSize


def create_image_widget(image_url, is_self, show_context_menu, download_image):
    frame = QFrame()
    frame.setStyleSheet("""
        QFrame {
            background-color: white;
            border-radius: 10px;
            border: 1px solid #ddd;
            padding: 5px;
        }
    """ if not is_self else """
        QFrame {
            background-color: #DCF8C6;
            border-radius: 10px;
            padding: 5px;
        }
    """)
    frame.setMaximumWidth(400)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(5, 5, 5, 5)
    layout.setSpacing(5)

    pixmap = None
    file_name = None
    try:
        response = requests.get(image_url, timeout=10)
        if response.status_code == 200:
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)

            try:
                from urllib.parse import urlparse, unquote
                parsed_url = urlparse(image_url)
                file_name = unquote(os.path.basename(parsed_url.path))
                if not file_name or '.' not in file_name:
                    content_type = response.headers.get('Content-Type', '')
                    ext = 'jpg'
                    if 'png' in content_type:
                        ext = 'png'
                    elif 'gif' in content_type:
                        ext = 'gif'
                    elif 'webp' in content_type:
                        ext = 'webp'
                    file_name = f"image_{int(time.time())}.{ext}"
            except Exception:
                file_name = f"image_{int(time.time())}.jpg"

            if pixmap.width() > 400:
                pixmap = pixmap.scaledToWidth(400, Qt.SmoothTransformation)

            image_container = QFrame()
            image_container.setStyleSheet("background-color: transparent;")
            image_layout = QVBoxLayout(image_container)
            image_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel()
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignCenter)
            label.setContextMenuPolicy(Qt.CustomContextMenu)
            label.customContextMenuRequested.connect(
                lambda pos: show_context_menu(image_url, file_name, label.mapToGlobal(pos))
            )
            image_layout.addWidget(label)
            layout.addWidget(image_container)

            btn_download = QPushButton("Tải ảnh xuống")
            btn_download.setStyleSheet("""
                QPushButton {
                    background-color: #f5f5f5;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    padding: 5px 10px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border: 1px solid #2196F3;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
            """ if not is_self else """
                QPushButton {
                    background-color: #c8e6c9;
                    border: 1px solid #4caf50;
                    border-radius: 5px;
                    padding: 5px 10px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #a5d6a7;
                    border: 1px solid #2e7d32;
                }
                QPushButton:pressed {
                    background-color: #81c784;
                }
            """)
            btn_download.clicked.connect(lambda: download_image(image_url, file_name))
            layout.addWidget(btn_download)
        else:
            error_label = QLabel("Không thể tải ảnh")
            error_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(error_label)
    except Exception as e:
        error_label = QLabel(f"Lỗi tải ảnh: {str(e)}")
        error_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(error_label)

    return frame


def create_audio_widget(audio_url, file_name, is_self, toggle_play_pause_cb, download_voice_cb, seek_callback, remove_widget_cb=None):
    frame = QFrame()
    frame.setStyleSheet("""
        QFrame {
            background-color: white;
            border-radius: 10px;
            border: 1px solid #ddd;
            padding: 10px;
        }
    """ if not is_self else """
        QFrame {
            background-color: #DCF8C6;
            border-radius: 10px;
            padding: 10px;
        }
    """)
    frame.setMaximumWidth(400)
    frame.setMinimumWidth(300)

    main_layout = QVBoxLayout(frame)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(8)

    header_layout = QHBoxLayout()
    header_layout.setSpacing(8)

    try:
        icon = qta.icon('fa.microphone', color='#666' if not is_self else '#4caf50')
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(24, 24))
    except Exception:
        icon_label = QLabel("🎤")
        icon_label.setFont(QFont("Arial", 14))

    label_name = QLabel(f"Voice: {file_name}")
    label_name.setWordWrap(True)
    label_name.setFont(QFont("Arial", 10))
    label_name.setStyleSheet("font-weight: bold;")

    header_layout.addWidget(icon_label)
    header_layout.addWidget(label_name)
    header_layout.addStretch()

    btn_download = QPushButton()
    try:
        btn_download.setIcon(qta.icon('fa.download', color='#666'))
        btn_download.setIconSize(QSize(16, 16))
    except Exception:
        btn_download.setText("📥")
    btn_download.setToolTip("Tải voice xuống")
    btn_download.setFixedSize(28, 28)
    btn_download.setStyleSheet("""
        QPushButton {
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: transparent;
        }
        QPushButton:hover {
            background-color: #f0f0f0;
            border: 1px solid #2196F3;
        }
    """)
    btn_download.clicked.connect(lambda: download_voice_cb(audio_url, file_name))
    header_layout.addWidget(btn_download)

    main_layout.addLayout(header_layout)

    controls_layout = QHBoxLayout()
    controls_layout.setSpacing(8)

    btn_play_pause = QPushButton("▶")
    btn_play_pause.setFixedSize(36, 36)
    btn_play_pause.setStyleSheet("""
        QPushButton {
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 18px;
            font-size: 14px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
    """)
    btn_play_pause.clicked.connect(lambda: toggle_play_pause_cb(audio_url, frame, btn_play_pause))

    progress_layout = QVBoxLayout()
    progress_layout.setSpacing(2)

    progress_slider = QSlider(Qt.Horizontal)
    progress_slider.setRange(0, 0)
    progress_slider.setStyleSheet("""
        QSlider::groove:horizontal {
            border: 1px solid #ddd;
            height: 4px;
            background: #e0e0e0;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #4CAF50;
            border: 1px solid #45a049;
            width: 12px;
            height: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }
        QSlider::sub-page:horizontal {
            background: #4CAF50;
            border-radius: 2px;
        }
    """)
    if seek_callback:
        progress_slider.sliderMoved.connect(lambda pos, w=frame: seek_callback(w, pos))

    time_label = QLabel("00:00 / 00:00")
    time_label.setFont(QFont("Arial", 9))
    time_label.setStyleSheet("color: #666;")
    time_label.setProperty('is_time_label', True)

    progress_layout.addWidget(progress_slider)
    progress_layout.addWidget(time_label)

    controls_layout.addWidget(btn_play_pause)
    controls_layout.addLayout(progress_layout)

    main_layout.addLayout(controls_layout)

    frame.setProperty('audio_url', audio_url)
    frame.setProperty('btn_play_pause', btn_play_pause)
    frame.setProperty('progress_slider', progress_slider)
    frame.setProperty('time_label', time_label)
    frame.setProperty('file_name', file_name)
    if remove_widget_cb:
        frame.setProperty('remove_widget_cb', remove_widget_cb)

    return frame


def create_file_widget(file_url, file_name, is_self, download_file):
    frame = QFrame()
    frame.setStyleSheet("""
        QFrame {
            background-color: white;
            border-radius: 10px;
            border: 1px solid #ddd;
            padding: 10px;
        }
    """ if not is_self else """
        QFrame {
            background-color: #DCF8C6;
            border-radius: 10px;
            padding: 10px;
        }
    """)
    frame.setMaximumWidth(300)

    layout = QHBoxLayout(frame)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(10)

    try:
        icon = qta.icon('fa.file', color='#666')
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
    except Exception:
        icon_label = QLabel("📎")
        icon_label.setFont(QFont("Arial", 20))

    label_name = QLabel(file_name)
    label_name.setWordWrap(True)
    label_name.setFont(QFont("Arial", 11))

    btn_download = QPushButton("Tải xuống")
    btn_download.setStyleSheet("""
        QPushButton {
            background-color: #2196F3;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 5px;
            font-size: 10px;
        }
        QPushButton:hover {
            background-color: #1976D2;
        }
    """)
    btn_download.clicked.connect(lambda: download_file(file_url, file_name))

    layout.addWidget(icon_label)
    layout.addWidget(label_name)
    layout.addWidget(btn_download)

    return frame


