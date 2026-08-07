"""Отбор по периоду выполняется базой, а не перебором в Python (PERF-1).

Месяц хранился именем («January»), а имена несравнимы по порядку: SQL ограничивал
выборку годами, поэтому из базы поднимался весь диапазон лет целиком, а лишние
записи отбрасывались уже в Python — одинаковым кодом в двух контроллерах.

Проверяется и результат (границы периода, переход через год), и то, что условие
действительно попало в запрос: иначе отбор продолжил бы работать, просто снова
после выборки.
"""

import unittest
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from controllers.AirlineIndController import AirlineIndController
from controllers.AirportIndController import AirportIndController
from controllers.period_filter import apply_period_filter, period_bounds
from db.models.entities import (
    Airline, AirlineIndicators, Airport, AirportIndicators, Indicator, Locality, Route, Shipping
)
from db.models.enums import Months, RouteType, ShippingRegularity
from db.models.types import MonthNumber
from tests.support import MigratedDbCase, scalar

# Отчётность за три месяца подряд, переходящая через год: именно здесь прежний
# фильтр «по годам» и промахивался.
PERIODS = [(2024, Months.November), (2024, Months.December), (2025, Months.January), (2025, Months.February)]


class MonthNumberTypeTest(unittest.TestCase):
    """Как месяц выглядит в базе и что возвращается в Python."""

    def setUp(self):
        self.type = MonthNumber()

    def test_month_is_stored_as_its_number(self):
        self.assertEqual(1, self.type.process_bind_param(Months.January, None))
        self.assertEqual(12, self.type.process_bind_param(Months.December, None))

    def test_name_is_accepted_too(self):
        """Парсеры отдают имя месяца — оно тоже должно приводиться к номеру."""
        self.assertEqual(3, self.type.process_bind_param("March", None))

    def test_number_comes_back_as_enum(self):
        self.assertEqual(Months.March, self.type.process_result_value(3, None))

    def test_out_of_range_is_refused(self):
        with self.assertRaises(ValueError):
            self.type.process_bind_param(13, None)

    def test_none_stays_none(self):
        self.assertIsNone(self.type.process_bind_param(None, None))
        self.assertIsNone(self.type.process_result_value(None, None))


class PeriodBoundsTest(unittest.TestCase):
    """Границы периода — одно число ГГГГММ."""

    def test_bounds_are_packed(self):
        filters = {"period_from": (2024, 11), "period_to": (2025, 2)}
        self.assertEqual((202411, 202502), period_bounds(filters))

    def test_no_period_means_no_bounds(self):
        self.assertIsNone(period_bounds({}))
        self.assertIsNone(period_bounds({"period_from": (2024, 11)}))


class PeriodInSqlTest(unittest.TestCase):
    """Условие периода должно оказаться в самом запросе."""

    def test_query_mentions_the_month(self):
        query = apply_period_filter(
            select(AirlineIndicators), AirlineIndicators,
            {"period_from": (2024, 11), "period_to": (2025, 2)},
        )

        sql = str(query.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("month", sql)
        self.assertIn("BETWEEN", sql.upper())
        self.assertIn("202411", sql)

    def test_query_without_period_is_untouched(self):
        base = select(AirlineIndicators)

        self.assertIs(base, apply_period_filter(base, AirlineIndicators, {}))


class PeriodSelectionCase(MigratedDbCase):
    """Отбор на настоящей базе: записи за четыре соседних месяца."""

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
            session.flush()
            for number, (year, month) in enumerate(PERIODS, start=1):
                session.add(AirlineIndicators(
                    id=number, indicator_id=1, shipping_id=1,
                    month=month, year=year, value=Decimal(number),
                ))
                session.add(AirportIndicators(
                    id=number, indicator_id=1, airport_id=1,
                    month=month, year=year, value=Decimal(number),
                ))
            session.commit()

    def airline_periods(self, filters):
        with self.Session() as session:
            rows = AirlineIndController.filter_indicators(session, filters)
        return sorted((r.year, r.month.name) for r in rows)

    def airport_periods(self, filters):
        with self.Session() as session:
            rows = AirportIndController.filter_indicators(session, filters)
        return sorted((r.year, r.month.name) for r in rows)


class PeriodSelectionTest(PeriodSelectionCase):

    def test_stored_as_numbers(self):
        self.assertEqual(11, scalar(self.engine, "SELECT month FROM airlineInd WHERE id = 1"))

    def test_range_crossing_the_year_boundary(self):
        """Декабрь 2024 — январь 2025: две записи из четырёх."""
        filters = {"period_from": (2024, 12), "period_to": (2025, 1)}

        self.assertEqual([(2024, "December"), (2025, "January")], self.airline_periods(filters))

    def test_bounds_are_inclusive(self):
        filters = {"period_from": (2024, 11), "period_to": (2025, 2)}

        self.assertEqual(4, len(self.airline_periods(filters)))

    def test_month_outside_the_range_is_dropped_within_the_same_year(self):
        """Ноябрь 2024 не входит в период с декабря 2024 — прежде это решалось в Python."""
        filters = {"period_from": (2024, 12), "period_to": (2024, 12)}

        self.assertEqual([(2024, "December")], self.airline_periods(filters))

    def test_empty_range_returns_nothing(self):
        filters = {"period_from": (2023, 1), "period_to": (2023, 12)}

        self.assertEqual([], self.airline_periods(filters))

    def test_without_period_everything_is_returned(self):
        self.assertEqual(4, len(self.airline_periods({})))

    def test_airport_branch_filters_the_same_way(self):
        filters = {"period_from": (2024, 12), "period_to": (2025, 1)}

        self.assertEqual([(2024, "December"), (2025, "January")], self.airport_periods(filters))


class LegacyMonthNamesTest(MigratedDbCase):
    """Накопленные записи с именами месяцев переводятся миграцией."""

    def test_names_became_numbers(self):
        # База поднята до актуальной ревизии в setUp; проверяем сам перевод на
        # значениях, записанных до неё.
        from alembic import command

        from db.migrator import _config
        from tests.support import db_url

        command.downgrade(_config(db_url(self.engine)), "c8f1b4d27a63")
        with self.engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(text(
                "INSERT INTO airlines (id, code, name) VALUES (1, 'AAA', 'АК')"
            ))
            conn.execute(text(
                "INSERT INTO routes (id, type, regularity) VALUES (1, 'trunk', 'regular')"
            ))
            conn.execute(text("INSERT INTO shipping (id, route_id, airline_id) VALUES (1, 1, 1)"))
            conn.execute(text(
                "INSERT INTO indicators (id, name, code, measure) VALUES (1, 'Налет часов', '356', 'час.')"
            ))
            conn.execute(text(
                "INSERT INTO airlineInd (id, indicator_id, shipping_id, month, year, value) "
                "VALUES (1, 1, 1, 'December', 2024, '5')"
            ))

        from db.migrator import upgrade_to_head

        upgrade_to_head(self.engine)

        self.assertEqual(12, scalar(self.engine, "SELECT month FROM airlineInd WHERE id = 1"))
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with Session() as session:
            self.assertEqual(Months.December, session.get(AirlineIndicators, 1).month)


if __name__ == "__main__":
    unittest.main()
