"""Свод: одноимённые месяцы разных лет — разные колонки (DATA-1).

Дефект был не в падении, а в правдоподобной неверной цифре: ключом группировки
служил месяц без года, поэтому январь 2024 и январь 2025 складывались в одну
колонку с подписью «Январь». Ни одного признака в интерфейсе при этом не было.

Записи собираются заглушками, а не через ORM: построителям нужны только атрибуты
показателя, рейса и периода, а поднимать ради этого полный граф связей значило бы
проверять SQLAlchemy вместо логики свода. Справочник показателей при этом настоящий —
построители читают его из БД.
"""

import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from controllers.data_controller import (
    DataController,
    _period_col_key,
    _period_count,
    _period_label,
    _sorted_periods,
    EMPTY_PERIOD,
)
from db.models.entities import Airline, Indicator
from db.models.enums import Months, RouteType, ShippingRegularity
from tests.support import MigratedDbCase


class FakeAirline:
    def __init__(self, aid: int, name: str):
        self.id = aid
        self.name = name


class FakeRoute:
    def __init__(self, route_type: str, regularity: str):
        self.type = RouteType[route_type]
        self.regularity = ShippingRegularity[regularity]


class FakeShipping:
    def __init__(self, airline: FakeAirline, route: FakeRoute):
        self.airline = airline
        self.route = route


class FakeIndicator:
    def __init__(self, code: str, name: str, measure: str, iid: int = 1):
        self.id = iid
        self.code = code
        self.name = name
        self.measure = measure


class FakeRecord:
    """Запись отчётности в том виде, в каком её видят построители свода."""

    def __init__(self, code, name, month, year, value, *, measure="тыс.сам.-км",
                 airline=("Тестовая АК", 1), route_type="trunk", regularity="regular"):
        self.indicator = FakeIndicator(code, name, measure)
        self.shipping = FakeShipping(FakeAirline(airline[1], airline[0]),
                                     FakeRoute(route_type, regularity))
        self.month = Months[month]
        self.year = year
        self.value = Decimal(str(value))
        self.airport = None


class PeriodHelpersTest(unittest.TestCase):
    """Помощники периода — то, чем заменён прежний ключ «только месяц»."""

    def test_periods_are_ordered_chronologically(self):
        periods = {(2025, "January"), (2024, "December"), (2024, "January")}
        self.assertEqual(
            _sorted_periods(periods),
            [(2024, "January"), (2024, "December"), (2025, "January")],
        )

    def test_column_key_contains_the_year(self):
        self.assertNotEqual(
            _period_col_key((2024, "January")),
            _period_col_key((2025, "January")),
        )

    def test_label_names_the_year(self):
        self.assertEqual(_period_label((2025, "January")), "Январь 2025")

    def test_empty_period_is_not_counted(self):
        """Заглушка пустой выборки — кортеж, а он истинен: считать её нельзя."""
        self.assertEqual(_period_count([EMPTY_PERIOD]), 0)
        self.assertEqual(_period_count([(2025, "January")]), 1)


class PivotCase(MigratedDbCase):
    """Построители свода на подменённой выборке и настоящем справочнике показателей."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Indicator(name="Самолето-километры", code="965", measure="тыс.сам.-км"))
            session.add(Indicator(name="Налет часов", code="356", measure="час."))
            # Свод по одной АК читает её название из БД по id.
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.commit()

        session_patch = patch("controllers.data_controller.get_session", self.Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)

        self.controller = DataController()

    def build_all_airlines(self, records):
        with patch(
            "controllers.data_controller.AirlineIndicatorService.filter_indicators",
            return_value=records,
        ):
            return self.controller._load_pivot_all_airlines({"any": "filter"})

    def build_per_airline_summary(self, records):
        with patch(
            "controllers.data_controller.AirlineIndicatorService.filter_indicators",
            return_value=records,
        ):
            return self.controller._load_pivot_per_airline_summary({}, airline_id=1)

    @staticmethod
    def row_for_code(result, code):
        for row in result["rows"]:
            if row.get("code") == code:
                return row
        raise AssertionError(f"в своде нет строки с кодом {code}")


class TwoYearPivotTest(PivotCase):
    """Тот самый сценарий DATA-1."""

    JANUARY_TWO_YEARS = None

    def setUp(self):
        super().setUp()
        self.records = [
            FakeRecord("965", "Самолето-километры", "January", 2024, 100),
            FakeRecord("965", "Самолето-километры", "January", 2025, 200),
        ]

    def test_columns_are_separate_per_year(self):
        result = self.build_all_airlines(self.records)
        row = self.row_for_code(result, "965")
        self.assertEqual(row["m_2024_January_total"], 100)
        self.assertEqual(row["m_2025_January_total"], 200)

    def test_values_are_not_summed_into_one_column(self):
        """Прежде здесь была одна колонка «Январь» со значением 300."""
        result = self.build_all_airlines(self.records)
        row = self.row_for_code(result, "965")
        self.assertNotIn("m_January_total", row)
        self.assertNotIn(300, [row["m_2024_January_total"], row["m_2025_January_total"]])

    def test_labels_name_the_year(self):
        result = self.build_all_airlines(self.records)
        labels = [group[2] for group in result["groups"]]
        self.assertEqual(labels, ["Январь 2024", "Январь 2025"])

    def test_two_periods_are_counted(self):
        result = self.build_all_airlines(self.records)
        self.assertEqual(result["stats"]["months"], 2)


class PeriodOrderTest(PivotCase):
    def test_december_precedes_january_of_the_next_year(self):
        records = [
            FakeRecord("965", "Самолето-километры", "January", 2025, 1),
            FakeRecord("965", "Самолето-километры", "December", 2024, 2),
        ]
        labels = [group[2] for group in self.build_all_airlines(records)["groups"]]
        self.assertEqual(labels, ["Декабрь 2024", "Январь 2025"])


class EmptySelectionTest(PivotCase):
    def test_empty_selection_reports_no_periods(self):
        result = self.build_all_airlines([])
        self.assertEqual(result["stats"]["months"], 0)


class SummaryTotalTest(PivotCase):
    """Свод по одной АК: «Всего» — сумма показанных колонок."""

    def test_total_sums_the_displayed_periods(self):
        records = [
            FakeRecord("965", "Самолето-километры", "January", 2024, 100),
            FakeRecord("965", "Самолето-километры", "January", 2025, 200),
        ]
        result = self.build_per_airline_summary(records)
        row = self.row_for_code(result, "965")
        self.assertEqual(row["m_2024_January"], 100)
        self.assertEqual(row["m_2025_January"], 200)
        self.assertEqual(row["total"], 300)

    def test_headers_name_the_year(self):
        records = [FakeRecord("965", "Самолето-километры", "March", 2025, 5)]
        result = self.build_per_airline_summary(records)
        self.assertIn("Март 2025", result["headers"])


if __name__ == "__main__":
    unittest.main()
