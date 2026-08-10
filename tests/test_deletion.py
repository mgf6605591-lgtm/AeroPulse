"""Удаление отчётности живёт в службе, а не в слоте Qt (ARCH-16).

Порядок «копия базы → удаление → журнал» — правило работы с отчётностью: отменить
удаление нечем (FUNC-6), а по журналу потом видно, что пропало (FUNC-5). Правило
это лежало в `MainWindow.delete_records`, и проверить его можно было только
глазами: позвать слот без экрана нельзя, а модальное окно остановило бы прогон.

Здесь оно проверяется прогоном — так же, как проверяется импорт. Главная из
проверок ниже — `test_backup_predates_the_deletion`: копия, снятая после удаления,
выглядит как копия, но не восстанавливает ничего.
"""
import os
import re
import sqlite3
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy.orm import sessionmaker

from db.models.entities import (
    Airline,
    AirlineIndicators,
    Airport,
    AirportIndicators,
    ImportLog,
    Indicator,
    Locality,
    Route,
    Shipping,
)
from db.models.enums import Months, RouteType, ShippingRegularity
from services.deletion_service import delete_indicators
from tests.support import MigratedDbCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DeletionCase(MigratedDbCase):
    """Три строки 12-ГА и одна 15-ГА на своей базе; копия ложится туда же."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.add(Route(id=1, type=RouteType.trunk, regularity=ShippingRegularity.regular))
            session.add(Shipping(id=1, route_id=1, airline_id=1))
            session.add(Locality(id=1, name="Город"))
            session.add(Airport(id=1, code="XXX", name="Аэропорт", locality_id=1))
            session.add(Indicator(id=1, name="Налет часов", code="356", measure="час."))
            session.commit()
        with self.Session() as session:
            # Месяцы разные: ключ отчётной строки — один показатель на рейс за
            # месяц, и три январские строки база не примет.
            months = (Months.January, Months.February, Months.March)
            for number, month in enumerate(months, start=1):
                session.add(AirlineIndicators(
                    id=number, indicator_id=1, shipping_id=1,
                    month=month, year=2025, value=Decimal(number),
                ))
            session.add(AirportIndicators(
                id=1, indicator_id=1, airport_id=1,
                month=Months.January, year=2025, value=Decimal("9"),
            ))
            session.commit()

        # Служба и журнал открывают свои сессии; база у теста своя.
        for target in ("services.deletion_service.get_session",
                       "services.journal_service.get_session"):
            patcher = patch(target, self.Session)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Копия снимается с того файла, который назовёт db_path().
        path_patch = patch("services.deletion_service.db_path", lambda: Path(self.db_path))
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def airline_ids(self):
        with self.Session() as session:
            return sorted(row_id for (row_id,) in session.query(AirlineIndicators.id).all())

    def airport_ids(self):
        with self.Session() as session:
            return sorted(row_id for (row_id,) in session.query(AirportIndicators.id).all())

    def journal_rows(self):
        with self.Session() as session:
            return session.query(ImportLog).filter(ImportLog.kind == "delete").all()


class RowsAreRemovedTest(DeletionCase):
    def test_listed_rows_are_gone(self):
        delete_indicators("airline", [1, 2])

        self.assertEqual([3], self.airline_ids())

    def test_count_tells_what_actually_went(self):
        """Строку могли удалить в другом окне: несуществующий id — не ошибка."""
        result = delete_indicators("airline", [1, 999])

        self.assertEqual(1, result.deleted)
        self.assertEqual([2, 3], self.airline_ids())

    def test_airport_rows_are_deleted_by_their_own_kind(self):
        result = delete_indicators("airport", [1])

        self.assertEqual(1, result.deleted)
        self.assertEqual([], self.airport_ids())

    def test_the_other_form_is_untouched(self):
        """Вид отчётности выбирает таблицу: 12-ГА не должна задеть 15-ГА."""
        delete_indicators("airline", [1, 2, 3])

        self.assertEqual([], self.airline_ids())
        self.assertEqual([1], self.airport_ids())

    def test_unknown_kind_is_refused_and_deletes_nothing(self):
        """Прежде вид отчётности выбирала ветка `else`: не 12-ГА — значит, аэропорты."""
        with self.assertRaises(ValueError):
            delete_indicators("самолёты", [1, 2, 3])

        self.assertEqual([1, 2, 3], self.airline_ids())
        self.assertEqual([1], self.airport_ids())


class BackupTest(DeletionCase):
    def test_backup_predates_the_deletion(self):
        """Копия, снятая после удаления, не восстанавливает ничего.

        Проверяется не порядок вызовов, а результат: в копии удалённая строка
        обязана быть — иначе копия бесполезна ровно в том случае, ради которого
        снималась.
        """
        result = delete_indicators("airline", [1, 2, 3])

        self.assertIsNotNone(result.backup)
        connection = sqlite3.connect(str(result.backup))
        try:
            saved = connection.execute("SELECT id FROM airlineInd ORDER BY id").fetchall()
        finally:
            connection.close()
        self.assertEqual([(1,), (2,), (3,)], saved)

    def test_backup_failure_does_not_stop_the_deletion(self):
        """Копия важна, но не важнее того, ради чего пользователь пришёл."""
        with patch("services.deletion_service.make_backup", side_effect=OSError("нет места")):
            result = delete_indicators("airline", [1])

        self.assertIsNone(result.backup)
        self.assertEqual(1, result.deleted)
        self.assertEqual([2, 3], self.airline_ids())

    def test_failed_backup_is_named_in_the_journal(self):
        """Иначе по журналу не отличить удаление с копией от удаления без неё."""
        with patch("services.deletion_service.make_backup", side_effect=OSError("нет места")):
            delete_indicators("airline", [1])

        (row,) = self.journal_rows()
        self.assertEqual("копия базы не снята", row.message)


class JournalTest(DeletionCase):
    def test_deletion_leaves_a_row(self):
        delete_indicators("airline", [1, 2], user="ваня")

        (row,) = self.journal_rows()
        self.assertEqual(2, row.removed)
        self.assertEqual("airline", row.entity_type)
        self.assertEqual("ваня", row.user)

    def test_journal_names_the_backup(self):
        result = delete_indicators("airline", [1])

        (row,) = self.journal_rows()
        self.assertIn(result.backup.name, row.message)


class DeletionNeedsNoWindowTest(unittest.TestCase):
    """То, ради чего правило и переехало из окна."""

    def test_service_imports_without_pyqt(self):
        script = (
            "import sys\n"
            "sys.modules['PyQt6'] = None\n"
            "import services.deletion_service  # noqa: F401\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_no_window_opens_a_session_or_touches_the_fact_tables(self):
        """Проверка на будущее: следующее удаление не должно приехать обратно в окно."""
        forbidden = re.compile(r"\bget_session\b|\bAirlineIndicators\b|\bAirportIndicators\b")
        offenders = [
            str(path.relative_to(PROJECT_ROOT / "forms"))
            for path in (PROJECT_ROOT / "forms").rglob("*.py")
            if forbidden.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
