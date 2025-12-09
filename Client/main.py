import sys
import asyncio

from PyQt5.QtWidgets import QApplication

import qasync

try:
    from Client.ui_login import MainWindow
except Exception:
    from ui_login import MainWindow


def main():
    app = QApplication(sys.argv)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    main_window = MainWindow()
    main_window.show()

    try:
        with loop:
            loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

import sys

from PyQt5.QtWidgets import QApplication
from ui_login import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
