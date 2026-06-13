import os
import sys

from utils.qt_plugins import ensure_qt_platform_plugins

ensure_qt_platform_plugins()

from PyQt6.QtWidgets import QApplication
from db.database import init_db
from forms.auth import Auth
from utils.paths import get_app_dir


def main():
    # Рабочая директория = каталог exe (PyInstaller) или корень проекта (разработка).
    try:
        os.chdir(get_app_dir())
    except OSError:
        pass

    # Инициализация БД (создание таблиц + миграция year)
    init_db()

    app = QApplication(sys.argv)
    window = Auth()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
