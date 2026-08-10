# forms/widgets/account_dialogs.py
"""Окна учётных записей: первичная настройка и смена пароля (SEC-1, SEC-2).

Первичная настройка заменила засев `admin/123`. Пустая таблица пользователей —
это первый запуск: программа не пускает в систему, а просит завести администратора.
Отменить окно можно, но тогда работать не с чем — приложение закрывается.

Смена пароля показывается принудительно тем учёткам, чей открытый пароль перевела
в хеш миграция `b7a4c9f21e05`: само значение к тому моменту уже могло разойтись.
"""
from forms.widgets.dialog_buttons import set_caption
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
)

from db.models.enums import UserPosition
from services.auth_service import auth_service
from utils.passwords import MIN_PASSWORD_LENGTH


def _password_field() -> QLineEdit:
    """Поле пароля со скрытым вводом (SEC-4) — везде одинаковое."""
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


class FirstRunDialog(QDialog):
    """Создание первого администратора при пустой базе."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Первичная настройка")
        self.setMinimumWidth(420)
        self._build()

    def _build(self) -> None:
        layout = QFormLayout(self)

        info = QLabel(
            "База данных пуста — в ней ещё нет ни одной учётной записи.\n"
            "Создайте администратора: логин и пароль задаёте вы, "
            "учётной записи по умолчанию в программе нет."
        )
        info.setWordWrap(True)
        layout.addRow(info)

        self.username = QLineEdit()
        layout.addRow("Логин:", self.username)

        self.email = QLineEdit()
        layout.addRow("Эл. почта:", self.email)

        self.password = _password_field()
        layout.addRow("Пароль:", self.password)

        self.confirm = _password_field()
        layout.addRow("Повтор пароля:", self.confirm)

        hint = QLabel(f"Не короче {MIN_PASSWORD_LENGTH} символов.")
        hint.setWordWrap(True)
        layout.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        set_caption(buttons, QDialogButtonBox.StandardButton.Ok, "Создать")
        set_caption(buttons, QDialogButtonBox.StandardButton.Cancel, "Выйти")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.account = None

    def _submit(self) -> None:
        # Пароль не обрезается по краям: пробел в нём — такой же значащий символ,
        # как любой другой (BUG-28).
        password = self.password.text()
        if password != self.confirm.text():
            QMessageBox.warning(self, "Внимание", "Пароли не совпадают.")
            self.confirm.clear()
            self.confirm.setFocus()
            return

        result = auth_service.create_account(
            self.username.text(),
            self.email.text(),
            password,
            position=UserPosition.admin,
        )
        if not result["success"]:
            QMessageBox.warning(self, "Внимание", result["message"])
            return

        self.account = result["account"]
        self.accept()


def ensure_initial_admin(parent=None) -> bool:
    """Первый запуск: заводит администратора. False — пользователь отказался.

    Вызывается после создания QApplication и до окна входа: пускать в форму входа
    при пустой таблице пользователей бессмысленно — подойти к ней не с чем.
    """
    if auth_service.has_users():
        return True
    return FirstRunDialog(parent).exec() == QDialog.DialogCode.Accepted


class PasswordChangeDialog(QDialog):
    """Смена пароля. При обязательной смене окно нельзя пропустить."""

    def __init__(self, account, forced: bool = False, parent=None):
        super().__init__(parent)
        self.account = account
        self.forced = forced
        self.setWindowTitle("Смена пароля")
        self.setMinimumWidth(420)
        self._build()

    def _build(self) -> None:
        layout = QFormLayout(self)

        if self.forced:
            text = (
                "Пароль этой учётной записи хранился в базе открытым текстом и был "
                "известен всем, у кого есть файл базы или копия репозитория.\n"
                "Задайте новый пароль — без этого вход не будет продолжен."
            )
        else:
            text = "Задайте новый пароль."
        info = QLabel(text)
        info.setWordWrap(True)
        layout.addRow(info)

        self.new_password = _password_field()
        layout.addRow("Новый пароль:", self.new_password)

        self.confirm = _password_field()
        layout.addRow("Повтор пароля:", self.confirm)

        hint = QLabel(f"Не короче {MIN_PASSWORD_LENGTH} символов.")
        hint.setWordWrap(True)
        layout.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        set_caption(buttons, QDialogButtonBox.StandardButton.Ok, "Сохранить")
        if self.forced:
            set_caption(buttons, QDialogButtonBox.StandardButton.Cancel, "Отменить вход")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _submit(self) -> None:
        password = self.new_password.text()
        if password != self.confirm.text():
            QMessageBox.warning(self, "Внимание", "Пароли не совпадают.")
            self.confirm.clear()
            self.confirm.setFocus()
            return

        result = auth_service.change_password(self.account.id, password)
        if not result["success"]:
            QMessageBox.warning(self, "Внимание", result["message"])
            return

        self.account = result["account"]
        self.accept()
