import sys

import matplotlib
matplotlib.use("QtAgg")

from PySide6.QtWidgets import QApplication

from app.database import init_db
from app.ui.main_window import MainWindow


def main() -> None:
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName("TradeLedger")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
