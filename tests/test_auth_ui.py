"""Окна входа и учётных записей (SEC-4, SEC-2).

Слой Qt до сих пор не был покрыт тестами вообще. Здесь проверяется то, что нельзя
увидеть в самих службах: свойство поля пароля в загруженной разметке и поведение
диалогов первичной настройки и обязательной смены пароля.

Окна создаются на платформе offscreen — ни одного окна на экране не появляется.
Модальные QMessageBox подменяются: без этого отказ в диалоге остановил бы прогон.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from services.auth_service import auth_service
from tests.support import MigratedDbCase, scalar
from utils.passwords import is_hashed

try:
    from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AuthWindowTest(unittest.TestCase):
    """Разметка окна входа."""

    def test_password_field_is_masked(self):
        """SEC-4: без echoMode пароль виден на экране целиком."""
        from forms.auth import Auth

        window = Auth()
        self.addCleanup(window.deleteLater)
        self.assertEqual(QLineEdit.EchoMode.Password, window.password.echoMode())

    def test_login_field_is_not_masked(self):
        from forms.auth import Auth

        window = Auth()
        self.addCleanup(window.deleteLater)
        self.assertEqual(QLineEdit.EchoMode.Normal, window.login.echoMode())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class RegisterButtonIsGoneTest(unittest.TestCase):
    """FUNC-3: кнопка «Зарегистрироваться» была видима и не делала ничего.

    Единственным способом получить доступ оставалась захардкоженная пара
    admin/123 (SEC-2). Её больше нет, а регистрация приложению не нужна вовсе:
    пользователь один, первую учётную запись заводит окно первичной настройки.
    Поэтому кнопка убрана, а не подключена.
    """

    def make_window(self):
        from forms.auth import Auth

        window = Auth()
        self.addCleanup(window.deleteLater)
        return window

    def test_window_has_no_register_button(self):
        window = self.make_window()

        captions = [b.text() for b in window.findChildren(QPushButton)]
        self.assertEqual(["Войти"], captions)

    def test_markup_file_declares_no_register_button(self):
        """И в файле разметки тоже: экранной проверки мало, файл лежит отдельно.

        Разметка разбирается как XML, а не ищется подстрокой: слово
        «Зарегистрироваться» осталось в комментарии, объясняющем, почему кнопки
        здесь нет, — и поиск по тексту спотыкался бы об это объяснение.
        """
        from forms.auth import Auth

        root = ElementTree.parse(Auth._resolve_auth_ui_path()).getroot()
        buttons = [
            widget.get("name") for widget in root.iter("widget")
            if widget.get("class") == "QPushButton"
        ]

        self.assertEqual(["loginBtn"], buttons)

    def test_stale_markup_next_to_the_exe_does_not_bring_it_back(self):
        """Разметка ищется в трёх местах, включая каталог рядом с exe.

        Устаревшая копия там вернула бы нерабочую кнопку на экран — ровно так же,
        как вернула бы видимый пароль (SEC-4).
        """
        from forms.auth import Auth

        # Разметка подделывается разбором XML, а не заменой подстроки. Прежде
        # здесь стоял якорь по тексту, и правка разметки под FUNC-8 его унесла:
        # замена перестала применяться, а страховка `assertIn` продолжала
        # срабатывать — на слове «Зарегистрироваться» в комментарии. Тест
        # оставался зелёным, ничего не проверяя.
        root = ElementTree.parse(Auth._resolve_auth_ui_path()).getroot()
        central = root.find(".//widget[@name='centralwidget']")
        self.assertIsNotNone(central, "в разметке нет центрального виджета")
        button = ElementTree.SubElement(
            central, "widget", {"class": "QPushButton", "name": "pushButton"}
        )
        caption = ElementTree.SubElement(button, "property", {"name": "text"})
        ElementTree.SubElement(caption, "string").text = "Зарегистрироваться"
        stale = ElementTree.tostring(root, encoding="unicode")

        self.assertIn('name="pushButton"', stale, "подделка разметки не удалась")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.ui"
            path.write_text(stale, encoding="utf-8")
            with patch.object(Auth, "_resolve_auth_ui_path", staticmethod(lambda: path)):
                window = self.make_window()

        captions = [b.text() for b in window.findChildren(QPushButton)]
        self.assertEqual(["Войти"], captions)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class LoginWindowIsLaidOutTest(unittest.TestCase):
    """FUNC-8: окно входа было размечено координатами, без единого компоновщика.

    Оно не масштабировалось, не подстраивалось под системный шрифт и под
    укрупнение интерфейса: подписи наезжали друг на друга. Класс формы и
    заголовок окна при этом назывались `MainWindow` — форма создавалась
    копированием шаблона главного окна и не переименовывалась.
    """

    def setUp(self):
        from forms.auth import Auth

        self.window = Auth()
        self.addCleanup(self.window.deleteLater)
        self.markup = ElementTree.parse(Auth._resolve_auth_ui_path()).getroot()

    def test_markup_uses_layouts(self):
        self.assertNotEqual([], self.markup.findall(".//layout"))

    def test_no_widget_is_placed_by_coordinates(self):
        """Своя геометрия остаётся только у самого окна — это его начальный размер."""
        placed = [
            widget.get("name")
            for widget in self.markup.iter("widget")
            if widget.find("property[@name='geometry']") is not None
            and widget.get("class") != "QMainWindow"
        ]
        self.assertEqual([], placed)

    def test_central_widget_has_a_layout(self):
        self.assertIsNotNone(self.window.centralWidget().layout())

    def test_fields_follow_the_window_size(self):
        """Поведенческая проверка: при фиксированных координатах поле не двигалось."""
        self.window.show()
        self.window.resize(340, 200)
        QApplication.processEvents()
        narrow = self.window.login.width()

        self.window.resize(700, 200)
        QApplication.processEvents()

        self.assertGreater(self.window.login.width(), narrow)

    def test_window_is_not_called_mainwindow_anymore(self):
        self.assertNotEqual("MainWindow", self.window.windowTitle())
        self.assertIn("AeroPulse", self.window.windowTitle())
        self.assertNotEqual("MainWindow", self.markup.findtext("class"))

    def test_template_leftovers_are_gone(self):
        """Пустые строка меню и строка состояния пришли из шаблона главного окна."""
        classes = {widget.get("class") for widget in self.markup.iter("widget")}

        self.assertNotIn("QMenuBar", classes)
        self.assertNotIn("QStatusBar", classes)

    def test_window_is_sized_for_a_login_form(self):
        """Прежде окно входа открывалось размером 800×600 — под главное окно."""
        rect = self.markup.find(".//widget[@class='QMainWindow']/property[@name='geometry']/rect")

        self.assertLessEqual(int(rect.findtext("width")), 500)
        self.assertLessEqual(int(rect.findtext("height")), 400)

    def test_enter_submits_the_form(self):
        """Кнопка по умолчанию: с формой на компоновщиках это стало уместно."""
        self.assertTrue(self.window.loginBtn.isDefault())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AccountDialogCase(MigratedDbCase):
    """Диалоги поверх временной БД, с подменённым модальным предупреждением."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        patcher = patch("services.auth_service.get_session", self.Session)
        patcher.start()
        self.addCleanup(patcher.stop)

        warning = patch("forms.widgets.account_dialogs.QMessageBox.warning")
        self.warning = warning.start()
        self.addCleanup(warning.stop)


class FirstRunDialogTest(AccountDialogCase):

    def make_dialog(self, username="admin", email="admin@localhost",
                    password="Пароль12345", confirm=None):
        from forms.widgets.account_dialogs import FirstRunDialog

        dialog = FirstRunDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.username.setText(username)
        dialog.email.setText(email)
        dialog.password.setText(password)
        dialog.confirm.setText(password if confirm is None else confirm)
        return dialog

    def test_fields_are_masked(self):
        dialog = self.make_dialog()
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.password.echoMode())
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.confirm.echoMode())

    def test_creates_administrator(self):
        dialog = self.make_dialog()

        dialog._submit()

        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual("admin", dialog.account.username)
        self.assertTrue(dialog.account.is_admin)
        self.assertTrue(is_hashed(
            scalar(self.engine, "SELECT password_hash FROM users WHERE username = 'admin'")
        ))

    def test_mismatched_confirmation_creates_nothing(self):
        dialog = self.make_dialog(confirm="Пароль12346")

        dialog._submit()

        self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(0, scalar(self.engine, "SELECT count(*) FROM users"))
        self.assertIn("не совпадают", self.warning.call_args.args[2])

    def test_short_password_creates_nothing(self):
        dialog = self.make_dialog(password="1234567")

        dialog._submit()

        self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(0, scalar(self.engine, "SELECT count(*) FROM users"))

    def test_dialog_is_skipped_when_accounts_exist(self):
        from forms.widgets.account_dialogs import ensure_initial_admin

        auth_service.create_account("admin", "admin@localhost", "Пароль12345")
        # Окно не создаётся вовсе: exec() модален и остановил бы прогон.
        self.assertTrue(ensure_initial_admin())


class PasswordChangeDialogTest(AccountDialogCase):

    def setUp(self):
        super().setUp()
        self.account = auth_service.create_account(
            "admin", "admin@localhost", "Пароль12345"
        )["account"]
        with self.Session() as session:
            session.execute(text("UPDATE users SET must_change_password = 1"))
            session.commit()

    def make_dialog(self, password="Новый пароль123", confirm=None):
        from forms.widgets.account_dialogs import PasswordChangeDialog

        dialog = PasswordChangeDialog(self.account, forced=True)
        self.addCleanup(dialog.deleteLater)
        dialog.new_password.setText(password)
        dialog.confirm.setText(password if confirm is None else confirm)
        return dialog

    def test_fields_are_masked(self):
        dialog = self.make_dialog()
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.new_password.echoMode())
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.confirm.echoMode())

    def test_saves_new_password_and_clears_the_flag(self):
        dialog = self.make_dialog()

        dialog._submit()

        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertFalse(dialog.account.must_change_password)
        self.assertTrue(auth_service.sign_in("admin", "Новый пароль123")["success"])

    def test_same_password_keeps_the_requirement(self):
        dialog = self.make_dialog(password="Пароль12345")

        dialog._submit()

        self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(
            1, scalar(self.engine, "SELECT must_change_password FROM users WHERE id = 1")
        )

    def test_mismatched_confirmation_keeps_the_requirement(self):
        dialog = self.make_dialog(confirm="Другой пароль123")

        dialog._submit()

        self.assertNotEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(
            1, scalar(self.engine, "SELECT must_change_password FROM users WHERE id = 1")
        )


if __name__ == "__main__":
    unittest.main()
