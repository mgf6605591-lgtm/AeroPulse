import sys
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from db.models.entities import User
from db.database import get_session
from services.auth_service import auth_service
from utils.paths import get_app_dir, resource_path

from controllers.UserController import UserController


class Auth(QMainWindow):
    def __init__(self):
        super().__init__()

        ui_path = self._resolve_auth_ui_path()
        uic.loadUi(str(ui_path), self)
        self.loginBtn.clicked.connect(self.login_action)

    @staticmethod
    def _resolve_auth_ui_path() -> Path:
        candidates = [
            resource_path("forms", "UIs", "auth.ui"),
            get_app_dir() / "forms" / "UIs" / "auth.ui",
            Path(__file__).resolve().parent / "UIs" / "auth.ui",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def login_action(self):
        username = self.login.text().strip()
        password = self.password.text().strip()

        if not username:
            QMessageBox.warning(self, "Внимание", "Введите логин!")
            self.login.setFocus()
            return

        if not password:
            QMessageBox.warning(self, "Внимание", "Введите пароль!")
            self.password.setFocus()
            return

        with get_session() as session:
            login_result = auth_service.login_user(session, username, password)
            if login_result:
                user = UserController.get_user_by_login(session, username)
                self.close()
                self.open_main_window(user)
            else:
                QMessageBox.warning(self, "Ошибка",
                    "Неверный логин или пароль!\nПроверьте введенные данные.")
                self.password.clear()
                self.password.setFocus()
                return

    def open_main_window(self, user):
        from forms.mainWin import MainWindow
        self.main_window = MainWindow(user)
        self.main_window.show()
