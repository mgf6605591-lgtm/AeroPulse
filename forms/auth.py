import sys
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDialog, QLineEdit, QMainWindow, QMessageBox
from forms.widgets.account_dialogs import PasswordChangeDialog
from services.auth_service import auth_service
from utils.paths import get_app_dir, resource_path


class Auth(QMainWindow):
    def __init__(self):
        super().__init__()

        ui_path = self._resolve_auth_ui_path()
        uic.loadUi(str(ui_path), self)
        # Скрытый ввод задан и в auth.ui, и здесь (SEC-4). Файл разметки ищется в трёх
        # местах, в том числе рядом с exe: устаревшая копия там снова показывала бы
        # пароль на экране, и заметить это можно было бы только глазами.
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
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
        # Пароль не обрезается: `.strip()` отсекал бы значащие символы, и с переходом
        # на хеширование пользователь с пробелом в пароле перестал бы входить без
        # каких-либо объяснений (BUG-28).
        password = self.password.text()

        if not username:
            QMessageBox.warning(self, "Внимание", "Введите логин!")
            self.login.setFocus()
            return

        if not password:
            QMessageBox.warning(self, "Внимание", "Введите пароль!")
            self.password.setFocus()
            return

        result = auth_service.sign_in(username, password)
        if not result["success"]:
            QMessageBox.warning(self, "Ошибка", result["message"])
            self.password.clear()
            self.password.setFocus()
            return

        account = result["account"]
        if account.must_change_password:
            dialog = PasswordChangeDialog(account, forced=True, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                # Отказ от смены — отказ от входа: прежний пароль остаётся известным.
                self.password.clear()
                self.password.setFocus()
                return
            account = dialog.account

        self.close()
        self.open_main_window(account)

    def open_main_window(self, user):
        from forms.mainWin import MainWindow
        self.main_window = MainWindow(user)
        self.main_window.show()
