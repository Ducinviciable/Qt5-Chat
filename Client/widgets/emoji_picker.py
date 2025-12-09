import qtawesome as qta
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QScrollArea,
    QHBoxLayout,
    QPushButton,
    QLabel,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class EmojiPicker(QWidget):

    emoji_selected = pyqtSignal(str)

    _EMOJI_CATEGORIES = {
        'Smileys': ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "🥲", "🥹",
                    "😊", "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗",
                    "😙", "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓"],
        'Gestures': ["👋", "🤚", "🖐", "✋", "🖖", "👌", "🤌", "🤏", "✌️", "🤞",
                     "🤟", "🤘", "🤙", "👈", "👉", "👆", "🖕", "👇", "☝️", "👍",
                     "👎", "✊", "👊", "🤛", "🤜", "👏", "🙌", "👐", "🤲", "🤝"],
        'Hearts': ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔",
                   "❤️‍🔥", "❤️‍🩹", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟"],
        'Objects': ["🔥", "💧", "⭐", "🌟", "✨", "💫", "⚡", "☄️", "💥", "💢",
                    "💯", "💤", "💨", "💬", "💭", "🗯", "💮", "💐", "🌹", "🥀"],
        'Food': ["🍕", "🍔", "🍟", "🌭", "🍿", "🧂", "🥓", "🥚", "🍳", "🧇",
                 "🥞", "🧈", "🍞", "🥐", "🥨", "🥯", "🥖", "🧀", "🥗", "🥙",
                 "🥪", "🌮", "🌯", "🥫", "🍝", "🍜", "🍲", "🍛", "🍣", "🍱"],
        'Activities': ["🎉", "🎊", "🎈", "🎁", "🎀", "🎗", "🎟", "🎫", "🎪", "🎭",
                       "🩰", "🎨", "🎬", "🎤", "🎧", "🎼", "🎹", "🥁", "🎷", "🎺",
                       "🎸", "🪗", "🎻", "🎲", "♟️", "🎯", "🎳", "🎮", "🎰", "🧩"],
    }

    _CATEGORY_ICONS = {
        'Smileys': 'fa.smile-o',
        'Gestures': 'fa.hand-o-up',
        'Hearts': 'fa.heart',
        'Objects': 'fa.star',
        'Food': 'fa.cutlery',
        'Activities': 'fa.gamepad',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(200)
        self.hide()
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #ddd; background-color: #fafafa; }
            QTabBar::tab { background-color: #f0f0f0; padding: 5px 10px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: white; border-bottom: 2px solid #2196F3; }
        """)

        for category, emojis in self._EMOJI_CATEGORIES.items():
            self._add_category_tab(category, emojis)

        main_layout.addWidget(self.tabs)

    def _add_category_tab(self, category: str, emojis: list[str]):
        tab_page = QWidget()
        tab_layout = QVBoxLayout(tab_page)
        tab_layout.setContentsMargins(5, 5, 5, 5)

        emoji_grid_widget = QWidget()
        grid_layout = QVBoxLayout(emoji_grid_widget)
        grid_layout.setSpacing(3)

        row_layout = None
        for index, emoji in enumerate(emojis):
            if index % 10 == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(3)
                grid_layout.addLayout(row_layout)

            btn = QPushButton(emoji)
            btn.setFixedSize(32, 32)
            btn.setFont(QFont("Segoe UI Emoji", 14))
            btn.setStyleSheet("""
                QPushButton {
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                    background-color: white;
                }
                QPushButton:hover {
                    background-color: #f0f0f0;
                    border: 1px solid #2196F3;
                }
                QPushButton:pressed {
                    background-color: #e3f2fd;
                }
            """)
            btn.clicked.connect(lambda _, e=emoji: self.emoji_selected.emit(e))
            row_layout.addWidget(btn)

        scroll = QScrollArea()
        scroll.setWidget(emoji_grid_widget)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background-color: transparent;")
        tab_layout.addWidget(scroll)

        icon_name = self._CATEGORY_ICONS.get(category, 'fa.tag')
        try:
            icon = qta.icon(icon_name, color='#2196F3')
            self.tabs.addTab(tab_page, icon, category)
        except Exception:
            self.tabs.addTab(tab_page, category)

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def hide_picker(self):
        self.hide()

    def show_picker(self):
        self.show()


