"""Журнал, резервные копии и замена периода (FUNC-5, FUNC-6, DATA-5).

Три пункта об одном: данные исчезали необратимо и бесследно.

* повторный импорт исправленного отчёта оставлял в базе строки, которых в новом
  файле уже нет, и свод показывал смесь двух версий (DATA-5);
* установить, из какого файла пришло значение, было нечем — имя файла жило только
  в сообщении на экране (FUNC-5);
* отмены нет, копий нет: диалог удаления честно предупреждал, что действие
  необратимо, и это была вся защита (FUNC-6).

Порядок здесь важен: удаление исчезнувших строк можно вводить только вместе с
журналом и копией, иначе это ещё один тихий способ потерять данные.
"""

import sqlite3
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from db.backup import backup_name, existing_backups, make_backup
from db.models.entities import Airline, AirlineIndicators, ImportLog, Shipping
from db.models.enums import Months
from importers.data_importer import DataImporter
from tests.support import MigratedDbCase


def indicator_row(code: str, value: str) -> dict:
    return {
        "indicator_code": code,
        "indicator_name": f"Показатель {code}",
        "measure": "ед.",
        "route_type": "trunk",
        "regularity": "regular",
        "value": Decimal(value),
    }


class PeriodReplacementCase(MigratedDbCase):
    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.commit()

    def payload(self, rows, month="March", year=2025, source_file="отчёт.xlsx"):
        return {
            "entity_type": "airline",
            "data_type": "airline",
            "entity_id": 1,
            "airline": {"name": "Тестовая АК", "id": 1},
            "month": month,
            "year": year,
            "source_file": source_file,
            "indicators": rows,
        }

    def do_import(self, rows, **kwargs):
        with self.Session() as session:
            result = DataImporter._import_airline_data(session, self.payload(rows, **kwargs))
            session.commit()
        return result

    def stored_codes(self, year=2025, month=Months.March):
        with self.Session() as session:
            return sorted(
                row.indicator.code
                for row in session.query(AirlineIndicators).all()
                if row.year == year and row.month == month
            )

    def journal(self):
        with self.Session() as session:
            return session.query(ImportLog).order_by(ImportLog.id).all()


class VanishedRowsTest(PeriodReplacementCase):
    """DATA-5: исправленный отчёт заменяет период целиком."""

    def test_row_missing_from_the_corrected_report_is_removed(self):
        self.do_import([indicator_row("965", "100"), indicator_row("642", "50")])

        result = self.do_import([indicator_row("965", "120")])

        self.assertEqual(["965"], self.stored_codes())
        self.assertEqual(1, result["removed"])

    def test_removal_is_reported_to_the_user(self):
        self.do_import([indicator_row("965", "100"), indicator_row("642", "50")])

        result = self.do_import([indicator_row("965", "120")])

        self.assertIn("Удалено строк", result["message"])

    def test_other_periods_are_untouched(self):
        """Заменяется период отчёта, а не вся отчётность предприятия."""
        self.do_import([indicator_row("965", "100")], month="February")

        self.do_import([indicator_row("642", "50")], month="March")

        self.assertEqual(["965"], self.stored_codes(month=Months.February))
        self.assertEqual(["642"], self.stored_codes(month=Months.March))

    def test_unchanged_report_removes_nothing(self):
        rows = [indicator_row("965", "100"), indicator_row("642", "50")]
        self.do_import(rows)

        result = self.do_import(rows)

        self.assertEqual(0, result["removed"])
        self.assertEqual(["642", "965"], self.stored_codes())


class JournalTest(PeriodReplacementCase):
    """FUNC-5: у каждой загрузки остаётся след."""

    def test_import_is_recorded(self):
        self.do_import([indicator_row("965", "100")])

        entry = self.journal()[-1]
        self.assertEqual("import", entry.kind)
        self.assertEqual("отчёт.xlsx", entry.source_file)
        self.assertEqual("Тестовая АК", entry.entity_name)
        self.assertEqual(Months.March, entry.month)
        self.assertEqual(2025, entry.year)
        self.assertEqual(1, entry.imported)

    def test_counters_tell_what_happened(self):
        self.do_import([indicator_row("965", "100"), indicator_row("642", "50")])

        self.do_import([indicator_row("965", "120")], source_file="исправленный.xlsx")

        entry = self.journal()[-1]
        self.assertEqual("исправленный.xlsx", entry.source_file)
        self.assertEqual(0, entry.imported)
        self.assertEqual(1, entry.updated)
        self.assertEqual(1, entry.removed)

    def test_every_import_leaves_a_row(self):
        self.do_import([indicator_row("965", "100")])
        self.do_import([indicator_row("965", "100")])

        self.assertEqual(2, len(self.journal()))

    def test_journal_survives_deletion_of_the_airline(self):
        """Журнал не ссылается на предприятие ключом: он должен пережить его удаление."""
        self.do_import([indicator_row("965", "100")])

        with self.Session() as session:
            # Порядок удаления — как того требуют внешние ключи: отчётность,
            # затем рейсы, затем само предприятие.
            session.query(AirlineIndicators).delete()
            session.query(Shipping).delete()
            session.query(Airline).delete()
            session.commit()

        self.assertEqual(1, len(self.journal()))
        self.assertEqual("Тестовая АК", self.journal()[0].entity_name)


class BackupTest(MigratedDbCase):
    """FUNC-6: копия базы перед необратимой операцией."""

    def test_backup_is_a_readable_database(self):
        copy = make_backup(Path(self.db_path), reason="delete")

        self.assertIsNotNone(copy)
        connection = sqlite3.connect(str(copy))
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
        finally:
            connection.close()
        self.assertIn("airlineInd", tables)

    def test_backup_keeps_the_data(self):
        with sessionmaker(bind=self.engine)() as session:
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.commit()

        copy = make_backup(Path(self.db_path), reason="delete")

        connection = sqlite3.connect(str(copy))
        try:
            names = [row[0] for row in connection.execute("SELECT name FROM airlines")]
        finally:
            connection.close()
        self.assertEqual(["Тестовая АК"], names)

    def test_name_says_when_and_why(self):
        name = backup_name("delete", datetime(2026, 8, 7, 19, 5, 1))

        self.assertEqual("database-20260807-190501-delete.db", name)

    def test_old_backups_are_rotated(self):
        for number in range(5):
            make_backup(Path(self.db_path), reason=f"n{number}", keep=3)

        self.assertEqual(3, len(existing_backups(Path(self.db_path))))

    def test_missing_database_is_not_an_error(self):
        """Копировать нечего — операция, ради которой копию снимали, продолжается."""
        self.assertIsNone(make_backup(Path(self.db_path).parent / "нет.db", reason="delete"))


if __name__ == "__main__":
    unittest.main()
