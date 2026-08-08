"""Фабрика сессий и запрос диапазона лет (PERF-5, PERF-9).

`sessionmaker` создавался заново при каждом обращении к `get_session()` — на
каждый список фильтра, каждую строку импорта, каждую перезагрузку отчёта
(PERF-5). Диапазон лет собирался четырьмя отдельными полными сканированиями
вместо одного запроса, и делалось это при сборке каждого виджета фильтров и при
каждом сбросе (PERF-9).

Запросы считаются по событию `before_cursor_execute` — тем же способом, каким
проверяется число запросов импорта в `tests/test_import.py`: считается то, что
дошло до драйвера, а не то, что казалось написанным.
"""

import unittest
from collections import Counter
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

import db.database as database
from controllers.filter_controller import FilterController
from controllers.reference_cache import ReferenceDataCache
from db.models.entities import Locality
from tests.support import MigratedDbCase


class SessionFactoryTest(unittest.TestCase):
    """Фабрика одна на приложение, а не одна на вызов."""

    def test_factory_is_built_once_for_the_module(self):
        self.assertIsInstance(database._session_factory, sessionmaker)

    def test_repeated_calls_do_not_build_new_factories(self):
        """Прежде `sessionmaker(...)` выполнялся при каждом входе в контекст."""
        with patch("db.database.sessionmaker") as factory:
            for _ in range(5):
                with database.get_session():
                    pass

        self.assertFalse(factory.called)


class SessionRollsBackOnFailureTest(MigratedDbCase):
    """Незавершённая работа не остаётся в базе, а исключение доходит до вызывающего.

    `close()` откатывает транзакцию и сам — это проверено, и данные не терялись
    и раньше. Откат в `get_session` стоит затем, чтобы намерение читалось на
    месте; проверка ниже закрепляет само поведение, а не способ его добиться.
    """

    def setUp(self):
        super().setUp()
        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        patcher = patch("db.database._session_factory", factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def localities(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT count(*) FROM airport_localities")).scalar()

    def test_unfinished_work_is_not_kept(self):
        with self.assertRaises(RuntimeError):
            with database.get_session() as session:
                session.add(Locality(id=1, name="Город"))
                session.flush()
                raise RuntimeError("сбой посреди работы")

        self.assertEqual(0, self.localities())

    def test_committed_work_survives(self):
        with database.get_session() as session:
            session.add(Locality(id=1, name="Город"))
            session.commit()

        self.assertEqual(1, self.localities())


class PeriodRangeTest(MigratedDbCase):
    """Диапазон лет: один запрос вместо четырёх, ответ прежний."""

    def setUp(self):
        super().setUp()
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        patcher = patch("controllers.filter_controller.get_session", Session)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.controller = FilterController(ReferenceDataCache())

    def add_years(self, table: str, years) -> None:
        """Отчётные строки за указанные годы — минимальным набором связей."""
        with self.engine.begin() as conn:
            conn.execute(text(
                "INSERT OR IGNORE INTO indicators (id, name, code, measure) "
                "VALUES (1, 'Налет часов', '356', 'час.')"
            ))
            if table == "airlineInd":
                conn.execute(text("INSERT OR IGNORE INTO airlines (id, code, name) VALUES (1, 'AAA', 'АК')"))
                conn.execute(text("INSERT OR IGNORE INTO routes (id, type, regularity) VALUES (1, 'trunk', 'regular')"))
                conn.execute(text("INSERT OR IGNORE INTO shipping (id, route_id, airline_id) VALUES (1, 1, 1)"))
                owner_column, owner_id = "shipping_id", 1
            else:
                conn.execute(text("INSERT OR IGNORE INTO airport_localities (id, name) VALUES (1, 'Город')"))
                conn.execute(text(
                    "INSERT OR IGNORE INTO airports (id, code, name, locality_id) VALUES (1, 'ЯКТ', 'Якутск', 1)"
                ))
                owner_column, owner_id = "airport_id", 1

            for n, year in enumerate(years, start=1):
                conn.execute(text(
                    f"INSERT INTO {table} (indicator_id, {owner_column}, month, year, value) "
                    f"VALUES (1, {owner_id}, {n}, {year}, '1')"
                ))

    def count_statements(self) -> Counter:
        counter = Counter()

        def count(conn, cursor, statement, params, context, executemany):
            counter[statement.lstrip().split()[0].upper()] += 1

        event.listen(self.engine, "before_cursor_execute", count)
        try:
            self.controller.get_period_range()
        finally:
            event.remove(self.engine, "before_cursor_execute", count)
        return counter

    def test_range_is_taken_in_a_single_query(self):
        """Прежде — по два запроса на таблицу, четыре полных сканирования."""
        self.add_years("airlineInd", (2023, 2025))

        self.assertEqual(1, self.count_statements()["SELECT"])

    def test_range_covers_both_forms(self):
        self.add_years("airlineInd", (2023, 2024))
        self.add_years("airportInd", (2022, 2026))

        min_year, max_year, min_month, max_month = self.controller.get_period_range()

        self.assertEqual((2022, 2026, 1, 12), (min_year, max_year, min_month, max_month))

    def test_range_of_a_single_table(self):
        self.add_years("airportInd", (2021, 2023))

        self.assertEqual((2021, 2023, 1, 12), self.controller.get_period_range())

    def test_empty_database_gives_the_fallback(self):
        self.assertEqual((2024, 2025, 1, 12), self.controller.get_period_range())


class ReferenceListsCarryOnlyRecordsTest(MigratedDbCase):
    """Пункта «Все» в списках больше нет — его все вызывающие отфильтровывали."""

    def setUp(self):
        super().setUp()
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        patcher = patch("controllers.filter_controller.get_session", Session)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.controller = FilterController(ReferenceDataCache())

        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO airlines (id, code, name) VALUES (1, 'AAA', 'Тестовая АК')"))
            conn.execute(text(
                "INSERT INTO indicators (id, name, code, measure) VALUES (1, 'Налет часов', '356', 'час.')"
            ))

    def test_entities_are_only_entities(self):
        from utils.constants import MODE_AIRLINE

        self.assertEqual([(1, "Тестовая АК")], self.controller.load_entities(MODE_AIRLINE))

    def test_indicators_are_only_indicators(self):
        self.assertEqual([(1, "Налет часов")], self.controller.load_indicators())

    def test_failure_gives_an_empty_list_not_a_lone_placeholder(self):
        with patch("controllers.filter_controller.get_session",
                   side_effect=RuntimeError("нет базы")):
            self.assertEqual([], self.controller.load_indicators())


if __name__ == "__main__":
    unittest.main()
