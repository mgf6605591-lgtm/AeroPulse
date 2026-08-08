# forms/app_controller.py
"""Владелец окон приложения (BUG-8).

Окна создавали друг друга и хранили друг друга в полях: окно входа держало
главное в `self.main_window`, главное при выходе клало новое окно входа в
`self.auth_window` — уже будучи закрытым. Получался цикл ссылок, в котором на
каждом входе-выходе оставалось по паре «мёртвых» окон вместе с их моделями
данных; удалить их было некому, потому что владельца ни у одного окна не было.

Здесь владелец один. Окна друг о друге не знают: вход сообщает об учётной
записи сигналом, главное окно — о просьбе выйти, а кто и чем их сменит, решает
контроллер. Он же единственный, кто держит ссылки, и он же удаляет отработавшее
окно через `deleteLater()`.

**Крестик закрывает программу, «Выход» возвращает ко входу.** Прежде разницы не
было видно: `quitOnLastWindowClosed` завершал приложение сам, стоило закрыть
последнее окно, — поэтому смена окон при выходе работала только благодаря тому,
что новое окно успевало появиться. Теперь приложение закрывается там, где это
решено явно, а не как побочный эффект порядка вызовов.
"""
import logging

from PyQt6.QtCore import QObject

from forms.auth import Auth
from forms.mainWin import MainWindow

log = logging.getLogger(__name__)


class AppController(QObject):
    """Показывает окно входа, меняет его на главное и обратно."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._auth = None
        self._main = None
        # Пока идёт смена окон, закрытие старого — часть замысла, а не просьба
        # пользователя закрыть программу.
        self._swapping = False

    def start(self) -> None:
        self._show_auth()

    # --- окна --------------------------------------------------------------

    def _show_auth(self) -> None:
        self._auth = Auth()
        self._auth.logged_in.connect(self._on_logged_in)
        self._auth.closed.connect(self._on_window_closed)
        self._auth.show()

    def _show_main(self, account) -> None:
        self._main = MainWindow(account)
        self._main.logout_requested.connect(self._on_logout_requested)
        self._main.closed.connect(self._on_window_closed)
        self._main.show()

    def _dispose(self, window) -> None:
        """Закрывает окно и отдаёт его на удаление.

        `deleteLater()`, а не просто снятие ссылки: у окна остаются потомки и
        подписки на сигналы, и удалять его безопасно только когда управление
        вернётся в цикл событий.
        """
        if window is None:
            return
        window.close()
        window.deleteLater()

    # --- переходы ----------------------------------------------------------

    def _swap(self, close, open_next) -> None:
        self._swapping = True
        try:
            self._dispose(close())
            open_next()
        finally:
            self._swapping = False

    def _on_logged_in(self, account) -> None:
        def close_auth():
            window, self._auth = self._auth, None
            return window

        self._swap(close_auth, lambda: self._show_main(account))

    def _on_logout_requested(self) -> None:
        log.info("Выход из системы: возврат к окну входа")

        def close_main():
            window, self._main = self._main, None
            return window

        self._swap(close_main, self._show_auth)

    def _on_window_closed(self) -> None:
        """Окно закрыл пользователь — значит, закрывает программу."""
        if self._swapping:
            return
        log.info("Окно закрыто пользователем: завершение работы")
        self._app.quit()
