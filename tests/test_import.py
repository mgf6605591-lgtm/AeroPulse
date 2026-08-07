"""Импортёр: связи детализации показателей и повторная загрузка того же отчёта."""

import unittest
from collections import Counter
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db.models.entities import (
    Airline, AirlineIndicators, Airport, AirportIndicators, Indicator, Locality
)
from importers.data_importer import DataImporter
from tests.support import MigratedDbCase


def indicator_row(code: str, name: str, value: str) -> dict:
    """Строка показателя в том виде, в каком её отдают парсеры 12-ГА."""
    return {
        "indicator_code": code,
        "indicator_name": name,
        "measure": "тыс. ткм",
        "route_type": "trunk",
        "regularity": "regular",
        "value": Decimal(value),
    }


# Детализация идёт до родителя: в бланке строка 450 стоит выше, но полагаться
# на порядок строк файла нельзя.
DETAIL_BEFORE_PARENT = [
    indicator_row("450пас", "      а) пассажирский", "1.5"),
    indicator_row("450гр", "      б) грузовой (вкл. срочный груз)", "2.5"),
    indicator_row("450пч", "      в) почтовый", "0.5"),
    indicator_row("450", "Выполненный тоннокилометраж", "4.5"),
    indicator_row("965", "Самолето-километры", "100"),
]


class ImportCase(MigratedDbCase):
    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(code="AAA", name="Тестовая АК"))
            session.commit()
            self.airline_id = session.query(Airline).one().id

    def payload(self, indicators, month="March", year=2025) -> dict:
        return {
            "entity_type": "airline",
            "data_type": "airline",
            "entity_id": self.airline_id,
            "airline": {"name": "Тестовая АК", "code": "AAA", "id": self.airline_id},
            "month": month,
            "year": year,
            "indicators": indicators,
        }

    def do_import(self, indicators, **kwargs) -> dict:
        with self.Session() as session:
            return DataImporter._import_airline_data(session, self.payload(indicators, **kwargs))

    def indicators_by_code(self) -> dict:
        with self.Session() as session:
            return {ind.code: ind for ind in session.query(Indicator).all()}


class DetailIndicatorLinkTest(ImportCase):
    """parent_id нужен своду 12-ГА для подраздела «в том числе»."""

    def test_detail_rows_linked_to_parent(self):
        self.do_import(DETAIL_BEFORE_PARENT)

        by_code = self.indicators_by_code()
        for code in ("450пас", "450гр", "450пч"):
            self.assertEqual(by_code["450"].id, by_code[code].parent_id, code)

    def test_ordinary_indicators_have_no_parent(self):
        self.do_import(DETAIL_BEFORE_PARENT)

        by_code = self.indicators_by_code()
        self.assertIsNone(by_code["450"].parent_id)
        self.assertIsNone(by_code["965"].parent_id)

    def test_link_repaired_on_next_import(self):
        """Показатели, загруженные до появления этой логики, чинятся при импорте."""
        self.do_import(DETAIL_BEFORE_PARENT)
        with self.Session() as session:
            session.query(Indicator).filter(Indicator.code == "450пас").one().parent_id = None
            session.commit()

        self.do_import(DETAIL_BEFORE_PARENT)

        by_code = self.indicators_by_code()
        self.assertEqual(by_code["450"].id, by_code["450пас"].parent_id)

    def test_no_parent_row_in_file(self):
        """Детализация без родителя не должна ронять импорт."""
        result = self.do_import([indicator_row("450пас", "      а) пассажирский", "1.5")])

        self.assertTrue(result["success"], result["message"])
        self.assertIsNone(self.indicators_by_code()["450пас"].parent_id)


class ReimportTest(ImportCase):
    def test_reimport_updates_instead_of_duplicating(self):
        self.do_import(DETAIL_BEFORE_PARENT)

        result = self.do_import(DETAIL_BEFORE_PARENT)

        self.assertEqual(0, result["imported"])
        self.assertEqual(len(DETAIL_BEFORE_PARENT), result["updated"])
        with self.Session() as session:
            self.assertEqual(len(DETAIL_BEFORE_PARENT), session.query(AirlineIndicators).count())

    def test_corrected_report_overwrites_value(self):
        self.do_import([indicator_row("965", "Самолето-километры", "100")])

        self.do_import([indicator_row("965", "Самолето-километры", "150")])

        with self.Session() as session:
            self.assertEqual(150.0, float(session.query(AirlineIndicators).one().value))

    def test_other_month_is_separate_row(self):
        self.do_import([indicator_row("965", "Самолето-километры", "100")], month="March")

        self.do_import([indicator_row("965", "Самолето-километры", "120")], month="April")

        with self.Session() as session:
            self.assertEqual(2, session.query(AirlineIndicators).count())


class IndicatorCodeTest(ImportCase):
    """Код показателя при создании справочной записи (BUG-1)."""

    def nameless(self, code: str, value: str) -> dict:
        row = indicator_row(code, "", value)
        row["indicator_name"] = ""
        return row

    def test_code_survives_an_empty_name(self):
        """`code or name[:10] if name else 'UNK'` Python читает как
        `(code or name[:10]) if name else 'UNK'` — при пустом имени код
        отбрасывался и подставлялось 'UNK'.
        """
        self.do_import([self.nameless("965", "100")])

        self.assertIn("965", self.indicators_by_code())

    def test_two_nameless_rows_do_not_collide(self):
        """Второй 'UNK' ронял импорт файла: код показателя уникален."""
        result = self.do_import([self.nameless("965", "100"), self.nameless("642", "200")])

        self.assertTrue(result["success"], result["message"])
        by_code = self.indicators_by_code()
        self.assertIn("965", by_code)
        self.assertIn("642", by_code)

    def test_repeated_name_does_not_swallow_another_code(self):
        """DATA-8: названия строк бланка повторяются по разделам.

        «Самолето-километры» стоит и в регулярных перевозках (965), и в
        нерегулярных (965н). Поиск по названию находил уже созданный 965, строка
        965н в справочнике не заводилась, а её значения ложились под чужой код —
        при том, что раздел свода перебирает свои коды и потому оставался пуст.
        """
        rows = [
            indicator_row("965", "Самолето-километры", "100"),
            indicator_row("965н", "Самолето-километры", "7"),
        ]

        self.do_import(rows)

        by_code = self.indicators_by_code()
        self.assertIn("965", by_code)
        self.assertIn("965н", by_code)
        self.assertNotEqual(by_code["965"].id, by_code["965н"].id)

    def test_values_stay_under_their_own_code(self):
        rows = [
            indicator_row("965", "Самолето-километры", "100"),
            indicator_row("965н", "Самолето-километры", "7"),
        ]

        self.do_import(rows)

        with self.Session() as session:
            values = {
                r.indicator.code: float(r.value)
                for r in session.query(AirlineIndicators).all()
            }
        self.assertEqual({"965": 100.0, "965н": 7.0}, values)

    def test_nameless_lookup_still_finds_by_name(self):
        """Запись без кода по-прежнему подхватывает показатель с тем же названием."""
        self.do_import([indicator_row("965", "Самолето-километры", "100")])
        row = indicator_row("", "Самолето-километры", "120")
        row["indicator_code"] = ""

        self.do_import([row])

        self.assertEqual(1, len(self.indicators_by_code()))

    def test_name_is_used_when_there_is_no_code(self):
        row = indicator_row("", "Показатель без кода", "1")
        row["indicator_code"] = ""

        self.do_import([row])

        # Код без кода — первые 10 символов названия.
        self.assertIn("Показатель", self.indicators_by_code())


class QueryCountTest(ImportCase):
    """Число запросов не растёт вместе с числом строк файла (PERF-3)."""

    def count_queries(self, indicators) -> Counter:
        counter = Counter()
        self.statements = []

        def count(conn, cursor, statement, params, context, executemany):
            counter[statement.lstrip().split()[0].upper()] += 1
            self.statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", count)
        try:
            with self.Session() as session:
                DataImporter._import_airline_data(session, self.payload(indicators))
                session.commit()
        finally:
            event.remove(self.engine, "before_cursor_execute", count)
        return counter

    @staticmethod
    def rows(count: int) -> list:
        return [indicator_row(f"K{n}", f"Показатель {n}", str(n)) for n in range(count)]

    def test_selects_do_not_grow_with_the_file(self):
        """Прежде на каждую строку приходилось по три-четыре отдельных запроса."""
        few = self.count_queries(self.rows(5))["SELECT"]
        many = self.count_queries(self.rows(50))["SELECT"]

        self.assertEqual(few, many)

    def test_selects_are_a_handful(self):
        """Справочники, рейсы и строки периода — по одному запросу, а не по строке."""
        self.assertLessEqual(self.count_queries(self.rows(50))["SELECT"], 10)

    def test_repeat_import_of_unchanged_report_writes_no_data(self):
        """Значения те же — в отчётность не пишется ничего.

        Строка журнала при этом добавляется: загрузка была, и она записана
        (FUNC-5). Поэтому проверяются обращения к таблице отчётности, а не
        общее число INSERT.
        """
        rows = self.rows(20)
        self.count_queries(rows)

        self.count_queries(rows)

        touching_data = [
            sql for sql in self.statements
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE")) and "airlineInd" in sql
        ]
        self.assertEqual([], touching_data)


class DuplicateRowsTest(ImportCase):
    """Повторяющаяся строка внутри одного файла (PERF-3, побочная выгода)."""

    def test_duplicate_key_updates_instead_of_breaking_the_import(self):
        """Прежде вторая такая строка роняла импорт файла по уникальному ключу."""
        rows = [
            indicator_row("965", "Самолето-километры", "100"),
            indicator_row("965", "Самолето-километры", "150"),
        ]

        result = self.do_import(rows)

        self.assertTrue(result["success"], result.get("message"))
        with self.Session() as session:
            row = session.query(AirlineIndicators).one()
            self.assertEqual(150.0, float(row.value))


class LockedOnce:
    """Сессия, которая один раз отвечает «database is locked».

    Так выглядит занятая другим процессом база SQLite — то, ради чего и написан
    механизм повтора.
    """

    def __init__(self, session):
        self._session = session
        self.failed = False

    def __getattr__(self, name):
        return getattr(self._session, name)

    def commit(self):
        if not self.failed:
            self.failed = True
            raise OperationalError("INSERT INTO ...", {}, Exception("database is locked"))
        return self._session.commit()


class DatabaseLockTest(MigratedDbCase):
    """Повтор при блокировке базы — одинаково для обеих веток импорта (BUG-23)."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.add(Locality(id=1, name="Город"))
            session.add(Airport(id=1, code="XXX", name="Тестовый аэропорт", locality_id=1))
            session.commit()

        # Повтор берёт новую сессию через get_session и ждёт между попытками.
        session_patch = patch("importers.data_importer.get_session", self.Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)
        sleep_patch = patch("importers.data_importer.time.sleep")
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def airport_payload(self):
        return {
            "entity_type": "airport",
            "data_type": "airport",
            "entity_id": 1,
            "airport": {"name": "Тестовый аэропорт", "id": 1},
            "month": "January",
            "year": 2025,
            "indicators": [{
                "indicator_code": "15ГА-R05-ВС",
                "indicator_name": "Внутренние регулярные — Воздушные суда",
                "measure": "ед.",
                "value": Decimal("610"),
            }],
        }

    def airline_payload(self):
        return {
            "entity_type": "airline",
            "data_type": "airline",
            "entity_id": 1,
            "airline": {"name": "Тестовая АК", "code": "AAA", "id": 1},
            "month": "January",
            "year": 2025,
            "indicators": [indicator_row("965", "Самолето-километры", "100")],
        }

    def test_airport_import_is_retried(self):
        """Прежде общий `except Exception` съедал блокировку, и повтор не начинался."""
        with self.Session() as session:
            result = DataImporter.import_data(LockedOnce(session), self.airport_payload())

        self.assertTrue(result["success"], result.get("message"))
        with self.Session() as session:
            self.assertEqual(1, session.query(AirportIndicators).count())

    def test_airline_import_is_retried(self):
        with self.Session() as session:
            result = DataImporter.import_data(LockedOnce(session), self.airline_payload())

        self.assertTrue(result["success"], result.get("message"))
        with self.Session() as session:
            self.assertEqual(1, session.query(AirlineIndicators).count())

    def test_other_database_errors_are_not_retried(self):
        """Не всякая ошибка базы — блокировка: повторять «no such table» незачем."""

        class BrokenOnce(LockedOnce):
            def commit(self):
                raise OperationalError("SELECT ...", {}, Exception("no such table: airportInd"))

        with self.Session() as session:
            result = DataImporter.import_data(BrokenOnce(session), self.airport_payload())

        self.assertFalse(result["success"])
        self.assertIn("Ошибка базы данных", result["message"])

    def test_unexpected_error_names_the_branch(self):
        class Failing(LockedOnce):
            def commit(self):
                raise ValueError("что-то пошло не так")

        with self.Session() as session:
            result = DataImporter.import_data(Failing(session), self.airport_payload())

        self.assertFalse(result["success"])
        self.assertIn("аэропорта", result["message"])


if __name__ == "__main__":
    unittest.main()
