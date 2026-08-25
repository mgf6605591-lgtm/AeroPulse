"""Каталог пользовательских данных и переезд из каталога программы.

До появления установщика база, её копии и журнал лежали рядом с exe, а README
просил ставить программу туда, где есть право записи. Каталог программы
принадлежит установщику: обновление перезаписывает его целиком, удаление сносит.
Данные, оставленные там, однажды исчезли бы вместе с прежней версией — молча и
все сразу.

Отдельная забота — переезд уже установленных копий. Он обязан быть либо полным,
либо не начинаться: у базы в режиме WAL часть данных лежит в отдельном файле
журнала, и перенести один файл из трёх значит получить повреждённую базу.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import logging_setup
from utils.paths import (
    APP_NAME,
    get_app_dir,
    get_data_dir,
    migrate_legacy_data_dir,
)


class DevelopmentDataDirTest(unittest.TestCase):
    """В разработке ничего не переезжает: каталог данных — корень проекта."""

    def test_data_dir_is_the_project_root(self):
        self.assertEqual(get_app_dir(), get_data_dir())

    def test_database_stays_where_the_developer_expects(self):
        from db import database

        self.assertEqual(get_app_dir() / "db" / "database.db", database.db_path())

    def test_log_stays_next_to_the_database(self):
        self.assertEqual(get_app_dir() / logging_setup.LOG_FILE_NAME,
                         logging_setup.log_path())


class InstalledDataDirTest(unittest.TestCase):
    """У установленной программы каталог данных задаёт операционная система."""

    def setUp(self):
        frozen = patch("utils.paths.is_frozen", return_value=True)
        frozen.start()
        self.addCleanup(frozen.stop)

        home = patch.object(Path, "home", staticmethod(lambda: Path("/дом")))
        home.start()
        self.addCleanup(home.stop)

    def test_windows_uses_local_appdata(self):
        with patch("utils.paths.sys.platform", "win32"), \
             patch.dict(os.environ, {"LOCALAPPDATA": "/профиль/Local"}):
            self.assertEqual(Path("/профиль/Local") / APP_NAME, get_data_dir())

    def test_windows_without_the_variable_falls_back_to_the_profile(self):
        """Переменной нет в урезанном окружении: служба, планировщик задач."""
        with patch("utils.paths.sys.platform", "win32"), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Path("/дом/AppData/Local") / APP_NAME, get_data_dir())

    def test_macos_uses_application_support(self):
        with patch("utils.paths.sys.platform", "darwin"), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Path("/дом/Library/Application Support") / APP_NAME,
                             get_data_dir())

    def test_linux_honours_xdg(self):
        with patch("utils.paths.sys.platform", "linux"), \
             patch.dict(os.environ, {"XDG_DATA_HOME": "/данные"}):
            self.assertEqual(Path("/данные") / APP_NAME, get_data_dir())

    def test_data_dir_is_never_the_program_dir(self):
        """Ради этого всё и затевалось."""
        with patch("utils.paths.sys.platform", "win32"), \
             patch.dict(os.environ, {"LOCALAPPDATA": "/профиль/Local"}):
            self.assertNotEqual(get_app_dir(), get_data_dir())


class LegacyMoveTest(unittest.TestCase):
    """Переезд базы, копий и журнала из каталога программы."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.source = root / "Программа"
        self.target = root / "Данные"
        self.source.mkdir()
        self.target.mkdir()

    def make_legacy(self, *, wal: bool = True, backups: int = 2,
                    logs: tuple[str, ...] = ("aeropulse.log", "aeropulse.log.1")):
        """Раскладка, которую оставляли версии до установщика."""
        (self.source / "db").mkdir(exist_ok=True)
        (self.source / "db" / "database.db").write_text("база", encoding="utf-8")
        if wal:
            (self.source / "db" / "database.db-wal").write_text("журнал", encoding="utf-8")
            (self.source / "db" / "database.db-shm").write_text("общая память", encoding="utf-8")
        if backups:
            (self.source / "db" / "backups").mkdir(exist_ok=True)
            for number in range(backups):
                (self.source / "db" / "backups" /
                 f"database-2026081{number}-120000-import.db").write_text(
                    f"копия {number}", encoding="utf-8")
        for name in logs:
            (self.source / name).write_text("строка журнала", encoding="utf-8")

    def move(self) -> list[str]:
        return migrate_legacy_data_dir(self.source, self.target)

    def test_database_moves_with_its_wal(self):
        """Без -wal и -shm переехала бы не база, а её часть."""
        self.make_legacy()

        self.move()

        for name in ("database.db", "database.db-wal", "database.db-shm"):
            self.assertTrue((self.target / "db" / name).is_file(), name)
        self.assertEqual("база",
                         (self.target / "db" / "database.db").read_text(encoding="utf-8"))

    def test_backups_move_too(self):
        self.make_legacy(backups=3)

        self.move()

        copies = sorted(p.name for p in (self.target / "db" / "backups").iterdir())
        self.assertEqual(3, len(copies))

    def test_rotated_logs_move_too(self):
        self.make_legacy(logs=("aeropulse.log", "aeropulse.log.1", "aeropulse.log.2"))

        self.move()

        moved = sorted(p.name for p in self.target.glob("aeropulse.log*"))
        self.assertEqual(["aeropulse.log", "aeropulse.log.1", "aeropulse.log.2"], moved)

    def test_nothing_is_left_behind(self):
        """Оставленная копия базы — это вторая база, о которой никто не помнит."""
        self.make_legacy()

        self.move()

        left = sorted(p.name for p in (self.source / "db").rglob("*") if p.is_file())
        self.assertEqual([], left)
        self.assertEqual([], list(self.source.glob("aeropulse.log*")))

    def test_it_says_what_it_moved(self):
        self.make_legacy(backups=1, logs=("aeropulse.log",))

        moved = self.move()

        self.assertIn("db/database.db", moved)
        self.assertIn("db/database.db-wal", moved)
        self.assertIn("aeropulse.log", moved)
        self.assertEqual(5, len(moved))

    def test_a_database_in_the_new_place_is_never_touched(self):
        """Там работают. Рядом с exe в этом случае лежит прошлое, а не данные."""
        self.make_legacy()
        (self.target / "db").mkdir(exist_ok=True)
        (self.target / "db" / "database.db").write_text("рабочая", encoding="utf-8")

        moved = self.move()

        self.assertEqual([], moved)
        self.assertEqual("рабочая",
                         (self.target / "db" / "database.db").read_text(encoding="utf-8"))
        # Журнал тоже остался на месте: переезд либо целиком, либо никак.
        self.assertTrue((self.source / "aeropulse.log").is_file())

    def test_empty_db_directory_does_not_block_the_move(self):
        """`db.database` заводит каталог базы при импорте — до самого переезда."""
        self.make_legacy()
        (self.target / "db").mkdir(exist_ok=True)

        moved = self.move()

        self.assertIn("db/database.db", moved)

    def test_without_a_legacy_database_nothing_moves(self):
        """Один журнал переносить незачем: данных, к которым он относится, нет."""
        (self.source / "aeropulse.log").write_text("строка", encoding="utf-8")

        moved = self.move()

        self.assertEqual([], moved)
        self.assertTrue((self.source / "aeropulse.log").is_file())

    def test_the_same_directory_is_a_noop(self):
        """Так выглядит запуск из исходников."""
        self.make_legacy()

        self.assertEqual([], migrate_legacy_data_dir(self.source, self.source))
        self.assertTrue((self.source / "db" / "database.db").is_file())

    def test_second_run_moves_nothing(self):
        self.make_legacy()

        self.move()

        self.assertEqual([], self.move())


class RelocationFailureTest(unittest.TestCase):
    """Неудачный переезд останавливает запуск, а не проходит незамеченным."""

    def setUp(self):
        logging_setup.reset_for_tests()
        self.addCleanup(logging_setup.reset_for_tests)

    def test_failure_is_returned_not_raised(self):
        """Поднять её здесь некому: ни окна, ни журнала ещё нет."""
        import main

        with patch.object(main, "migrate_legacy_data_dir",
                          side_effect=OSError("нет доступа")):
            moved, error = main._relocate_user_data()

        self.assertEqual([], moved)
        self.assertIsInstance(error, OSError)

    def test_startup_stops_and_says_why(self):
        """Пустая база на месте прежней выглядит как потеря всей отчётности."""
        import main

        with patch.object(main, "migrate_legacy_data_dir",
                          side_effect=OSError("нет доступа")), \
             patch.object(main, "setup_logging", return_value=None), \
             patch.object(main, "init_db") as init_db, \
             patch.object(main, "QApplication") as app_cls, \
             patch.object(main, "QMessageBox") as message_box, \
             patch.object(main.os, "chdir"):
            with self.assertRaises(SystemExit) as exit_code:
                main.main()

        self.assertEqual(1, exit_code.exception.code)
        init_db.assert_not_called()
        # Окно создано раньше сообщения, иначе показать его негде (BUG-15).
        app_cls.assert_called_once()
        text = message_box.critical.call_args.args[2]
        self.assertIn("нет доступа", text)

    def test_successful_move_does_not_stop_anything(self):
        import main

        with patch.object(main, "migrate_legacy_data_dir",
                          return_value=["db/database.db"]), \
             patch.object(main, "setup_logging", return_value=None), \
             patch.object(main, "init_db", side_effect=RuntimeError("дальше не идём")), \
             patch.object(main, "QApplication"), \
             patch.object(main, "QMessageBox") as message_box, \
             patch.object(main.os, "chdir"):
            with self.assertRaises(SystemExit):
                main.main()

        # Дошло до базы — значит, переезд запуску не помешал.
        self.assertIn("дальше не идём", message_box.critical.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
