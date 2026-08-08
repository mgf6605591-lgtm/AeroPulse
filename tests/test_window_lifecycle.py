"""Жизненный цикл окон: вход, выход, закрытие программы (BUG-8).

Окна создавали друг друга и хранили друг друга в полях: окно входа держало
главное, главное при выходе клало новое окно входа в своё поле — уже будучи
закрытым. Удалять их было некому, и на каждом входе-выходе оставалась пара
«мёртвых» окон вместе с моделями данных.

Проверяется не устройство, а следствие: после нескольких кругов «вошёл — вышел»
живо ровно одно окно. Счёт ведётся по сигналу `destroyed`, то есть по настоящему
удалению объекта, а не по снятию ссылки в Python.

Окна главного окна и входа подменены заместителями: пункт про владельца окон, а
не про их содержимое, и поднимать ради него базу с таблицами незачем. Отдельно
проверено, что настоящее окно входа никаких окон больше не создаёт.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QCoreApplication, QEvent, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMainWindow
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


if HAS_QT:
    from forms.app_controller import AppController

    class Census:
        """Учёт созданных и по-настоящему удалённых окон."""

        def __init__(self):
            self.born = []
            self.died = []

        def alive(self) -> int:
            return len(self.born) - len(self.died)

    class FakeWindow(QMainWindow):
        """Заместитель окна: настоящий QMainWindow, но без базы и таблиц."""

        closed = pyqtSignal()
        census = None
        kind = "окно"

        def __init__(self):
            super().__init__()
            kind = type(self).kind
            type(self).census.born.append(kind)
            # Сигнал приходит при удалении объекта C++, а не при снятии ссылки в
            # Python: именно это и требуется проверить.
            self.destroyed.connect(lambda: type(self).census.died.append(kind))

        def closeEvent(self, event):
            super().closeEvent(event)
            self.closed.emit()

    class FakeAuth(FakeWindow):
        logged_in = pyqtSignal(object)
        kind = "вход"

    class FakeMain(FakeWindow):
        logout_requested = pyqtSignal()
        kind = "главное"

        def __init__(self, account=None):
            super().__init__()
            self.account = account

    class RecordingApp:
        """Заместитель QApplication: интересует только просьба закрыться."""

        def __init__(self):
            self.quits = 0

        def quit(self):
            self.quits += 1


def drain_deletions():
    """Доводит до конца отложенные удаления (`deleteLater`).

    Без прогона цикла событий объект остаётся живым, и проверка «окон не
    накапливается» проходила бы или падала случайно.
    """
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.census = Census()
        FakeAuth.census = self.census
        FakeMain.census = self.census

        for name, fake in (("Auth", FakeAuth), ("MainWindow", FakeMain)):
            patcher = patch(f"forms.app_controller.{name}", fake)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = RecordingApp()
        self.controller = AppController(self.app)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        for window in (self.controller._auth, self.controller._main):
            if window is not None:
                window.close()
                window.deleteLater()
        drain_deletions()

    def log_in(self):
        self.controller._auth.logged_in.emit(SimpleNamespace(username="кто-то"))
        drain_deletions()

    def log_out(self):
        self.controller._main.logout_requested.emit()
        drain_deletions()


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WindowsReplaceEachOtherTest(ControllerCase):
    def test_start_shows_the_login_window(self):
        self.controller.start()

        self.assertIsInstance(self.controller._auth, FakeAuth)
        self.assertIsNone(self.controller._main)
        self.assertTrue(self.controller._auth.isVisible())

    def test_login_replaces_the_login_window_with_the_main_one(self):
        self.controller.start()

        self.log_in()

        self.assertIsNone(self.controller._auth)
        self.assertIsInstance(self.controller._main, FakeMain)
        self.assertTrue(self.controller._main.isVisible())

    def test_main_window_receives_the_account(self):
        self.controller.start()

        self.controller._auth.logged_in.emit(SimpleNamespace(username="ваня"))

        self.assertEqual("ваня", self.controller._main.account.username)

    def test_logout_returns_to_the_login_window(self):
        self.controller.start()
        self.log_in()

        self.log_out()

        self.assertIsNone(self.controller._main)
        self.assertIsInstance(self.controller._auth, FakeAuth)
        self.assertTrue(self.controller._auth.isVisible())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WindowsDoNotAccumulateTest(ControllerCase):
    """То самое следствие, ради которого пункт заведён."""

    def test_used_window_is_really_destroyed(self):
        self.controller.start()

        self.log_in()

        self.assertEqual(["вход"], self.census.died)

    def test_five_rounds_leave_one_window_alive(self):
        self.controller.start()
        for _ in range(5):
            self.log_in()
            self.log_out()

        self.assertEqual(1, self.census.alive())

    def test_every_round_creates_and_destroys_exactly_one_pair(self):
        self.controller.start()

        for _ in range(3):
            self.log_in()
            self.log_out()

        # Шесть окон отработали и удалены, седьмое — открытое окно входа.
        self.assertEqual(7, len(self.census.born))
        self.assertEqual(6, len(self.census.died))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ClosingTheWindowClosesTheProgramTest(ControllerCase):
    """Крестик закрывает программу; «Выход» — только возвращает ко входу."""

    def test_closing_the_main_window_quits(self):
        self.controller.start()
        self.log_in()

        self.controller._main.close()

        self.assertEqual(1, self.app.quits)

    def test_closing_the_login_window_quits(self):
        self.controller.start()

        self.controller._auth.close()

        self.assertEqual(1, self.app.quits)

    def test_logout_does_not_quit(self):
        self.controller.start()
        self.log_in()

        self.log_out()

        self.assertEqual(0, self.app.quits)

    def test_login_does_not_quit(self):
        self.controller.start()

        self.log_in()

        self.assertEqual(0, self.app.quits)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class LoginWindowCreatesNothingTest(unittest.TestCase):
    """Настоящее окно входа: об учётной записи оно только сообщает."""

    def setUp(self):
        from forms.auth import Auth

        self.window = Auth()
        self.addCleanup(self.window.deleteLater)
        self.window.login.setText("кто-то")
        self.window.password.setText("пароль")

    def test_successful_login_is_reported_by_a_signal(self):
        account = SimpleNamespace(must_change_password=False, username="кто-то")
        seen = []
        self.window.logged_in.connect(seen.append)

        with patch("forms.auth.auth_service.sign_in",
                   return_value={"success": True, "account": account}):
            self.window.login_action()

        self.assertEqual([account], seen)

    def test_window_holds_no_reference_to_another_window(self):
        """Прежде здесь появлялось поле `main_window` с главным окном внутри."""
        account = SimpleNamespace(must_change_password=False, username="кто-то")

        with patch("forms.auth.auth_service.sign_in",
                   return_value={"success": True, "account": account}):
            self.window.login_action()

        self.assertFalse(hasattr(self.window, "main_window"))
        self.assertFalse(hasattr(self.window, "open_main_window"))

    def test_failed_login_reports_nothing(self):
        seen = []
        self.window.logged_in.connect(seen.append)

        with patch("forms.auth.auth_service.sign_in",
                   return_value={"success": False, "message": "не тот пароль"}), \
             patch("forms.auth.QMessageBox.warning"):
            self.window.login_action()

        self.assertEqual([], seen)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class MainWindowReportsInsteadOfActingTest(unittest.TestCase):
    """Настоящее главное окно: о выходе и о закрытии оно только сообщает.

    Окно поднимается без своего `__init__`: заполнять его вкладками, фильтрами и
    обеими таблицами — значит поднимать базу, а проверяются здесь два сигнала.
    Заместитель для этого не годится: в тестах контроллера он свой, и настоящее
    окно осталось бы непокрытым — что и обнаружилось при прогоне на сломанном коде.
    """

    def setUp(self):
        from forms.mainWin import MainWindow

        self.window = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(self.window)
        self.addCleanup(self.window.deleteLater)

    def test_closing_is_reported(self):
        seen = []
        self.window.closed.connect(lambda: seen.append(1))

        self.window.close()

        self.assertEqual([1], seen)

    def test_confirmed_logout_is_reported(self):
        from PyQt6.QtWidgets import QMessageBox

        seen = []
        self.window.logout_requested.connect(lambda: seen.append(1))

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            self.window.logout_action()

        self.assertEqual([1], seen)

    def test_declined_logout_reports_nothing(self):
        from PyQt6.QtWidgets import QMessageBox

        seen = []
        self.window.logout_requested.connect(lambda: seen.append(1))

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            self.window.logout_action()

        self.assertEqual([], seen)

    def test_window_creates_no_login_window_of_its_own(self):
        """Прежде здесь появлялось поле `auth_window` — у уже закрытого окна."""
        from PyQt6.QtWidgets import QMessageBox

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            self.window.logout_action()

        self.assertFalse(hasattr(self.window, "auth_window"))


if __name__ == "__main__":
    unittest.main()
