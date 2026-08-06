"""Что схема гарантирует на уровне БД: внешние ключи, каскады, уникальные ключи.

Проверяется поведение при тех же прагмах, что настраивает приложение. Если
PRAGMA foreign_keys=ON уберут из db.database, эти тесты упадут.
"""

import unittest

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.support import MigratedDbCase, scalar, seed_reference_data

AIRPORT_ROW = (
    "INSERT INTO airportInd (indicator_id, airport_id, month, year, value) "
    "VALUES (:indicator_id, 1, :month, 2025, 1)"
)
AIRLINE_ROW = (
    "INSERT INTO airlineInd (indicator_id, shipping_id, month, year, value) "
    "VALUES (1, 1, :month, 2025, 1)"
)


class ForeignKeyTest(MigratedDbCase):
    def setUp(self):
        super().setUp()
        seed_reference_data(self.engine)

    def execute(self, sql, **params):
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def test_pragma_is_enabled(self):
        self.assertEqual(1, scalar(self.engine, "PRAGMA foreign_keys"))

    def test_report_row_with_unknown_indicator_rejected(self):
        with self.assertRaises(IntegrityError):
            self.execute(AIRPORT_ROW, indicator_id=999, month="January")

    def test_locality_with_airports_not_deletable(self):
        """Правка справочника населённых пунктов не должна стирать отчётность."""
        with self.assertRaises(IntegrityError):
            self.execute("DELETE FROM airport_localities WHERE id = 1")

    def test_indicator_with_reports_not_deletable(self):
        self.execute(AIRPORT_ROW, indicator_id=1, month="January")
        with self.assertRaises(IntegrityError):
            self.execute("DELETE FROM indicators WHERE id = 1")

    def test_airport_with_reports_not_deletable(self):
        """Удаление аэропорта не должно уносить накопленную отчётность (SCH-10).

        Прежде здесь стоял каскад, и одна строка справочника забирала с собой
        отчёты за все периоды. Вместо удаления такую запись помечают неактивной.
        """
        self.execute(AIRPORT_ROW, indicator_id=1, month="January")
        with self.assertRaises(IntegrityError):
            self.execute("DELETE FROM airports WHERE id = 1")
        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM airportInd"))

    def test_airline_with_shipping_not_deletable(self):
        """Запрет стоит на рейсах: рейс создаётся импортом, значит данные есть."""
        self.execute(AIRLINE_ROW, month="January")
        with self.assertRaises(IntegrityError):
            self.execute("DELETE FROM airlines WHERE id = 1")
        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM airlineInd"))

    def test_airport_without_reports_is_deletable(self):
        """Ошибочно заведённая запись удаляется как раньше."""
        self.execute("DELETE FROM airports WHERE id = 1")
        self.assertEqual(0, scalar(self.engine, "SELECT count(*) FROM airports"))

    def test_deleting_parent_indicator_clears_detail_link(self):
        self.execute(
            "INSERT INTO indicators (id, name, code, measure, parent_id) "
            "VALUES (2, 'а) пассажирский', '450пас', 'тыс. ткм', 1)"
        )
        self.execute("DELETE FROM indicators WHERE id = 1")
        self.assertIsNone(scalar(self.engine, "SELECT parent_id FROM indicators WHERE id = 2"))


class UniqueKeyTest(MigratedDbCase):
    def setUp(self):
        super().setUp()
        seed_reference_data(self.engine)

    def execute(self, sql, **params):
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def test_same_report_row_twice_rejected(self):
        """Один показатель на рейс за месяц — иначе свод удвоит суммы."""
        self.execute(AIRLINE_ROW, month="January")
        with self.assertRaises(IntegrityError):
            self.execute(AIRLINE_ROW, month="January")

    def test_same_indicator_in_other_month_allowed(self):
        self.execute(AIRLINE_ROW, month="January")
        self.execute(AIRLINE_ROW, month="February")
        self.assertEqual(2, scalar(self.engine, "SELECT count(*) FROM airlineInd"))

    def test_duplicate_shipping_rejected(self):
        with self.assertRaises(IntegrityError):
            self.execute("INSERT INTO shipping (route_id, airline_id) VALUES (1, 1)")

    def test_duplicate_route_rejected(self):
        with self.assertRaises(IntegrityError):
            self.execute("INSERT INTO routes (type, regularity) VALUES ('trunk', 'regular')")


if __name__ == "__main__":
    unittest.main()
