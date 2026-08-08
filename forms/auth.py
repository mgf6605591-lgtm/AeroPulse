from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QLineEdit, QMainWindow, QMessageBox, QPushButton
from forms.widgets.account_dialogs import PasswordChangeDialog
from services.auth_service import auth_service
from utils.paths import get_app_dir, resource_path


class Auth(QMainWindow):
    """Окно входа.

    Об учётной записи оно только сообщает: главное окно строит и показывает
    владелец жизненного цикла (`forms.app_controller`). Прежде окно входа
    создавало главное само и держало его в своём поле — уже закрытым (BUG-8).
    """

    logged_in = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()

        ui_path = self._resolve_auth_ui_path()
        uic.loadUi(str(ui_path), self)
        # Скрытый ввод задан и в auth.ui, и здесь (SEC-4). Файл разметки ищется в трёх
        # местах, в том числе рядом с exe: устаревшая копия там снова показывала бы
        # пароль на экране, и заметить это можно было бы только глазами.
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self._drop_stale_register_button()
        self.loginBtn.clicked.connect(self.login_action)

    def _drop_stale_register_button(self) -> None:
        """Убирает кнопку «Зарегистрироваться», если она пришла из старой разметки.

        Из `auth.ui` она удалена (FUNC-3): кнопка была видима, ни к чему не
        подключена и по нажатию не делала ничего. Регистрации в приложении нет и
        не предполагается — пользователь один, а первую учётную запись заводит
        окно первичной настройки (SEC-2).

        Проверка здесь по той же причине, по какой рядом задан `echoMode`:
        разметка ищется в трёх местах, включая каталог рядом с exe. Устаревшая
        копия там вернула бы нерабочую кнопку на экран, и заметить это можно было
        бы только глазами.
        """
        stale = self.findChild(QPushButton, "pushButton")
        if stale is not None:
            stale.setParent(None)
            stale.deleteLater()

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

        self.logged_in.emit(account)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.closed.emit()
