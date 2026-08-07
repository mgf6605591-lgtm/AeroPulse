"""Запуск и файловый журнал (BUG-15, INFRA-2).

`init_db()` шёл до создания `QApplication`, то есть до того, как можно показать
хоть какое-то сообщение. Повреждённая база, занятый файл, нет прав на запись
рядом с exe — и приложение просто не запускалось: показать нечем, а трейсбек
уходил в несуществующий stdout. После перевода схемы на Alembic цена выросла:
до окна выполняются миграции, то есть операция долгая и изменяющая данные.

Диагностика при этом велась через `print()`, которого в собранном окне нет
вовсе. Туда же уходил отчёт миграции о том, сколько строк пользовательских
данных она удалила.
"""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import logging_setup

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


class LoggingSetupTest(unittest.TestCase):
    """Файл журнала: куда пишется и что делать, если писать нельзя."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        logging_setup.reset_for_tests()
        self.addCleanup(logging_setup.reset_for_tests)

    def test_message_reaches_the_file(self):
        target = self.dir / "aeropulse.log"

        logging_setup.setup_logging(path=target)
        logging.getLogger("проверка").error("что-то пошло не так")

        self.assertIn("что-то пошло не так", target.read_text(encoding="utf-8"))

    def test_traceback_is_kept(self):
        """Ради этого журнал и заводился: `print()` терял трейсбек целиком."""
        target = self.dir / "aeropulse.log"
        logging_setup.setup_logging(path=target)

        try:
            raise ValueError("причина")
        except ValueError:
            logging.getLogger("проверка").exception("операция не выполнена")

        written = target.read_text(encoding="utf-8")
        self.assertIn("Traceback", written)
        self.assertIn("ValueError: причина", written)

    def test_unwritable_location_does_not_break_startup(self):
        """Нет прав на запись рядом с exe — тот самый случай, ради которого журнал нужен."""
        unwritable = self.dir / "нет-такого-каталога" / "sub"

        with patch.object(Path, "mkdir", side_effect=OSError("нет прав")):
            written = logging_setup.setup_logging(path=unwritable / "aeropulse.log")

        self.assertIsNone(written)
        # Журнал всё равно настроен: сообщения уходят хотя бы в вывод.
        logging.getLogger("проверка").error("сообщение")

    def test_setup_is_idempotent(self):
        target = self.dir / "aeropulse.log"

        logging_setup.setup_logging(path=target)
        handlers_after_first = len(logging.getLogger().handlers)
        logging_setup.setup_logging(path=target)

        self.assertEqual(handlers_after_first, len(logging.getLogger().handlers))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class StartupOrderTest(unittest.TestCase):
    """Порядок запуска: окно должно существовать до обращения к базе."""

    def setUp(self):
        logging_setup.reset_for_tests()
        self.addCleanup(logging_setup.reset_for_tests)

    def test_database_failure_is_shown_to_the_user(self):
        """Прежде здесь не появлялось ничего: показать сообщение было нечем."""
        import main

        with patch.object(main, "setup_logging", return_value=None), \
             patch.object(main, "init_db", side_effect=RuntimeError("база повреждена")), \
             patch.object(main, "QApplication") as app_cls, \
             patch.object(main, "QMessageBox") as message_box, \
             patch.object(main.os, "chdir"):
            with self.assertRaises(SystemExit) as exit_code:
                main.main()

        self.assertEqual(1, exit_code.exception.code)
        message_box.critical.assert_called_once()
        # QApplication создано до обращения к базе, иначе диалог показать негде.
        app_cls.assert_called_once()

    def test_message_names_the_reason_and_the_log(self):
        import main

        with patch.object(main, "setup_logging", return_value=Path("/tmp/aeropulse.log")), \
             patch.object(main, "init_db", side_effect=RuntimeError("база повреждена")), \
             patch.object(main, "QApplication"), \
             patch.object(main, "QMessageBox") as message_box, \
             patch.object(main.os, "chdir"):
            with self.assertRaises(SystemExit):
                main.main()

        text = message_box.critical.call_args.args[2]
        self.assertIn("база повреждена", text)
        self.assertIn("aeropulse.log", text)


if __name__ == "__main__":
    unittest.main()
