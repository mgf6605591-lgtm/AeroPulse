"""Своды читают агрегат, а не сами факты (PERF-2, ARCH-4).

Прежде каждый построитель поднимал из базы все записи отчётности с
присоединёнными связями и складывал их в Python — своим кодом, скопированным в
четыре места. Теперь суммы считает база, а обход бланка общий для всех сводов.

Проверяется, что путь действительно новый (выборка фактов не вызывается), что
числа от этого не изменились и что счётчик записей по-прежнему считает факты, а
не группы.
"""

import unittest
from decimal import Decimal

from sqlalchemy.orm import sessionmaker

from controllers.AirlineIndController import AirlineIndController
from db.models.entities import (
    Airline, AirlineIndicators, Indicator, Route, Shipping
)
from db.models.enums import Months, RouteType, ShippingRegularity
from tests.support import MigratedDbCase, PivotCase, FakeRecord


class PivotDoesNotLoadFactsTest(PivotCase):
    """Своды не должны обращаться к выборке фактов вовсе."""

    def setUp(self):
        super().setUp()
        self.records = [
            FakeRecord("965", "Самолето-километры", "January", 2025, 100),
            FakeRecord("356", "Налет часов", "January", 2025, 7),
        ]

    def build_without_facts(self, build):
        """Выборка фактов подменяется взрывающейся: любой её вызов провалит тест.

        Служба отдаёт факты только подробной таблице (`detail_rows`), и свод не
        должен трогать этот путь вовсе.
        """
        from unittest.mock import patch

        from tests.support import aggregate_rows

        with patch(
            "controllers.data_controller.AirlineIndicatorService.detail_rows",
            side_effect=AssertionError("свод читает факты вместо агрегата"),
        ), patch(
            "controllers.data_controller.AirlineIndicatorService.aggregate",
            return_value=aggregate_rows(self.records),
        ):
            return build()

    def test_all_airlines(self):
        result = self.build_without_facts(
            lambda: self.controller._load_pivot_all_airlines({"any": "filter"})
        )
        self.assertEqual(100, self.row_for_code(result, "965")["m_2025_January_total"])

    def test_per_airline_by_routes(self):
        result = self.build_without_facts(
            lambda: self.controller._load_pivot_per_airline({}, airline_id=1)
        )
        self.assertEqual(100, self.row_for_code(result, "965")["m_2025_January_rt_trunk"])

    def test_per_airline_summary(self):
        result = self.build_without_facts(
            lambda: self.controller._load_pivot_per_airline_summary({}, airline_id=1)
        )
        self.assertEqual(100, self.row_for_code(result, "965")["m_2025_January"])

    def test_multi_airline_by_routes(self):
        result = self.build_without_facts(
            lambda: self.controller._load_pivot_multi_airline_by_routes({"any": "filter"})
        )
        self.assertEqual(100, self.row_for_code(result, "965")["m_2025_January_aid_1_rt_trunk"])

    def test_records_count_counts_facts_not_groups(self):
        """В счётчике записей — число строк отчётности, как и раньше."""
        result = self.build_without_facts(
            lambda: self.controller._load_pivot_all_airlines({"any": "filter"})
        )
        self.assertEqual(2, result["stats"]["records"])


class AggregateNumbersTest(MigratedDbCase):
    """Что именно считает база."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add_all([
                Airline(id=1, code="AAA", name="Тестовая АК"),
                Route(id=1, type=RouteType.trunk, regularity=ShippingRegularity.regular),
                Shipping(id=1, route_id=1, airline_id=1),
                Indicator(id=1, name="Выполненный тоннокилометраж", code="450", measure="тыс. ткм"),
            ])
            session.flush()
            session.add_all([
                AirlineIndicators(id=1, indicator_id=1, shipping_id=1,
                                  month=Months.January, year=2024, value=Decimal("100.25")),
                AirlineIndicators(id=2, indicator_id=1, shipping_id=1,
                                  month=Months.January, year=2025, value=Decimal("200.75")),
            ])
            session.commit()

    def aggregate(self, filters=None):
        with self.Session() as session:
            return AirlineIndController.aggregate(session, filters or {})

    def test_years_stay_apart(self):
        """DATA-1 на уровне запроса: год входит в группировку."""
        rows = self.aggregate()

        self.assertEqual(
            {(2024, "January"), (2025, "January")},
            {(row.year, row.month.name) for row in rows},
        )

    def test_sums_match_the_stored_values(self):
        totals = {row.year: row.total for row in self.aggregate()}

        self.assertAlmostEqual(100.25, totals[2024], places=2)
        self.assertAlmostEqual(200.75, totals[2025], places=2)

    def test_period_filter_applies_to_the_aggregate(self):
        rows = self.aggregate({"period_from": (2025, 1), "period_to": (2025, 12)})

        self.assertEqual([2025], [row.year for row in rows])

    def test_group_carries_what_the_pivot_needs(self):
        row = self.aggregate()[0]

        self.assertEqual("450", row.indicator_code)
        self.assertEqual("Выполненный тоннокилометраж", row.indicator_name)
        self.assertEqual(RouteType.trunk, row.route_type)
        self.assertEqual(ShippingRegularity.regular, row.regularity)
        self.assertEqual(1, row.airline_id)
        self.assertEqual(1, row.records)


if __name__ == "__main__":
    unittest.main()
