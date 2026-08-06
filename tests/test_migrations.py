"""Прогон миграций: чистая база, перевод старых установок, схлопывание дублей."""

import unittest

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from db.migrator import upgrade_to_head
from db.models.entities import Base
from tests.support import (
    MigratedDbCase,
    TempDbCase,
    make_legacy_db,
    scalar,
    table_ddl,
)

EXPECTED_TABLES = {
    "users", "airlines", "airports", "airport_localities", "routes",
    "shipping", "indicators", "airlineInd", "airportInd",
}


class FreshDatabaseTest(MigratedDbCase):
    def test_creates_all_tables(self):
        self.assertTrue(EXPECTED_TABLES <= set(inspect(self.engine).get_table_names()))

    def test_schema_matches_model(self):
        """Главная страховка: линия ревизий не должна расходиться с моделью."""
        with self.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        self.assertEqual([], diff)

    def test_stops_at_single_head(self):
        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM alembic_version"))

    def test_second_run_changes_nothing(self):
        before = scalar(self.engine, "SELECT version_num FROM alembic_version")
        upgrade_to_head(self.engine)
        self.assertEqual(before, scalar(self.engine, "SELECT version_num FROM alembic_version"))


class LegacyDatabaseTest(TempDbCase):
    """Установки, созданные прежним create_all(): их нельзя пересоздавать с нуля."""

    def test_adopts_without_losing_data(self):
        make_legacy_db(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, username, email, position, password_hash) "
                "VALUES (1, 'admin', 'admin@localhost', 'admin', '123')"
            ))

        upgrade_to_head(self.engine)

        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM users"))
        self.assertEqual(
            "admin", scalar(self.engine, "SELECT username FROM users WHERE id = 1")
        )

    def test_adoption_applies_later_revisions(self):
        make_legacy_db(self.engine)
        self.assertNotIn("ON DELETE", table_ddl(self.engine, "airportInd"))

        upgrade_to_head(self.engine)

        self.assertIn("ON DELETE RESTRICT", table_ddl(self.engine, "airportInd"))
        self.assertIsNotNone(table_ddl(self.engine, "uq_airport_ind_period"))

    def test_restores_columns_added_by_old_init_db(self):
        """Совсем старые установки: year и parent_id дописывались вручную при запуске."""
        make_legacy_db(self.engine, without_year=True, without_parent_id=True)

        upgrade_to_head(self.engine)

        for table in ("airlineInd", "airportInd"):
            columns = {c["name"] for c in inspect(self.engine).get_columns(table)}
            self.assertIn("year", columns, table)
        indicator_columns = {c["name"] for c in inspect(self.engine).get_columns("indicators")}
        self.assertIn("parent_id", indicator_columns)

    def test_links_detail_indicators_once(self):
        """Разовый ремонт связей «в том числе» при переводе старой базы."""
        make_legacy_db(self.engine)
        with self.engine.begin() as conn:
            for ind_id, code in ((1, "450"), (2, "450пас")):
                conn.execute(
                    text("INSERT INTO indicators (id, name, code, measure) "
                         "VALUES (:id, :code, :code, 'тыс. ткм')"),
                    {"id": ind_id, "code": code},
                )

        upgrade_to_head(self.engine)

        self.assertEqual(
            1, scalar(self.engine, "SELECT parent_id FROM indicators WHERE code = '450пас'")
        )


class DuplicateCollapseTest(TempDbCase):
    """Дубли, накопленные до появления уникальных ключей, мешают их создать."""

    def setUp(self):
        super().setUp()
        make_legacy_db(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO airlines (id, code, name) VALUES (1, 'AAA', 'АК')"))
            conn.execute(text("INSERT INTO routes (id, type, regularity) VALUES (1, 'trunk', 'regular')"))
            conn.execute(text("INSERT INTO routes (id, type, regularity) VALUES (2, 'trunk', 'regular')"))
            conn.execute(text("INSERT INTO shipping (id, route_id, airline_id) VALUES (1, 1, 1)"))
            conn.execute(text("INSERT INTO shipping (id, route_id, airline_id) VALUES (2, 2, 1)"))
            conn.execute(text(
                "INSERT INTO indicators (id, name, code, measure) VALUES (1, 'Налет часов', '356', 'час.')"
            ))
            for row_id, shipping_id, value in ((1, 1, 10), (2, 2, 99)):
                conn.execute(
                    text("INSERT INTO airlineInd (id, indicator_id, shipping_id, month, year, value) "
                         "VALUES (:id, 1, :shipping_id, 'January', 2025, :value)"),
                    {"id": row_id, "shipping_id": shipping_id, "value": value},
                )

        upgrade_to_head(self.engine)

    def test_duplicate_reference_rows_merged(self):
        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM routes"))
        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM shipping"))

    def test_last_imported_report_row_wins(self):
        self.assertEqual(1, scalar(self.engine, "SELECT count(*) FROM airlineInd"))
        self.assertEqual(99.0, float(scalar(self.engine, "SELECT value FROM airlineInd")))

    def test_surviving_row_points_to_surviving_shipping(self):
        self.assertEqual(
            scalar(self.engine, "SELECT id FROM shipping"),
            scalar(self.engine, "SELECT shipping_id FROM airlineInd"),
        )


if __name__ == "__main__":
    unittest.main()
