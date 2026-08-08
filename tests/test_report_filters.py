"""Типизированный отбор для отчёта (ARCH-5).

Фильтры ехали через весь верхний слой обычным `dict`. Контракт нигде не был
описан и не проверялся: опечатка в ключе не вызывала ошибки — отбор просто молча
не применялся, и пользователь получал не тот отчёт, о котором думал.

Проверяется и сам контракт, и то, ради чего он заводился: опечатка теперь
падает, а парные ключи (`airline_id` при `airline_ids` и прочие) не хранятся —
одиночное значение выводится из списка.
"""

import os
import unittest
from dataclasses import FrozenInstanceError

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from controllers.filter_controller import FilterController
from controllers.period_filter import period_bounds
from controllers.report_filters import (
    NO_FILTERS,
    ReportFilters,
    with_airline,
    with_airport,
)
from utils.constants import MODE_AIRLINE, MODE_AIRPORT


class SingleValuesAreDerivedTest(unittest.TestCase):
    """Одиночные значения не хранятся: они и были производными от списка."""

    def test_one_element_gives_the_single_value(self):
        filters = ReportFilters(airline_ids=(7,))

        self.assertEqual(7, filters.airline_id)

    def test_several_elements_give_none(self):
        """Свод по одной АК строится, только когда она одна — это и был смысл ключа."""
        filters = ReportFilters(airline_ids=(7, 8))

        self.assertIsNone(filters.airline_id)

    def test_empty_gives_none(self):
        self.assertIsNone(ReportFilters().airline_id)

    def test_rule_is_the_same_for_every_pair(self):
        self.assertEqual(3, ReportFilters(airport_ids=(3,)).airport_id)
        self.assertEqual(5, ReportFilters(indicator_ids=(5,)).indicator_id)
        self.assertEqual("trunk", ReportFilters(route_types=("trunk",)).route_type)
        self.assertIsNone(ReportFilters(indicator_ids=(5, 6)).indicator_id)


class EntityIdAnswersOneQuestionTest(unittest.TestCase):
    """Прежде вызывающий перебирал четыре ключа подряд ради одного ответа."""

    def test_single_airline(self):
        self.assertEqual(7, ReportFilters(airline_ids=(7,)).entity_id)

    def test_single_airport(self):
        self.assertEqual(3, ReportFilters(airport_ids=(3,)).entity_id)

    def test_several_airlines_are_not_one_entity(self):
        self.assertIsNone(ReportFilters(airline_ids=(7, 8)).entity_id)

    def test_nothing_selected(self):
        self.assertIsNone(NO_FILTERS.entity_id)


class PeriodIsWholeOrNothingTest(unittest.TestCase):
    def test_both_bounds_make_a_period(self):
        filters = ReportFilters(period_from=(2025, 1), period_to=(2025, 3))

        self.assertEqual(((2025, 1), (2025, 3)), filters.period)

    def test_half_a_period_is_not_a_period(self):
        """Отбор по одной границе дал бы не тот срез, а не «почти тот»."""
        self.assertIsNone(ReportFilters(period_from=(2025, 1)).period)
        self.assertIsNone(ReportFilters(period_to=(2025, 3)).period)

    def test_sql_layer_reads_the_same_rule(self):
        self.assertIsNone(period_bounds(ReportFilters(period_from=(2025, 1))))
        self.assertEqual(
            (202501, 202503),
            period_bounds(ReportFilters(period_from=(2025, 1), period_to=(2025, 3))),
        )


class EmptinessMeansShowEverythingTest(unittest.TestCase):
    """Службы отличают «отбор задан» от «показать всё» проверкой `if filters`."""

    def test_empty_filters_are_falsy(self):
        self.assertFalse(NO_FILTERS)

    def test_any_field_makes_them_truthy(self):
        for filters in (
            ReportFilters(airline_ids=(1,)),
            ReportFilters(airport_ids=(1,)),
            ReportFilters(indicator_ids=(1,)),
            ReportFilters(route_types=("trunk",)),
            ReportFilters(period_from=(2025, 1), period_to=(2025, 1)),
            ReportFilters(pivot_table_layout="summary"),
        ):
            self.assertTrue(filters, filters)

    def test_half_a_period_alone_is_not_a_filter(self):
        """Половина периода в запрос не уходит — значит и отбором не является."""
        self.assertFalse(ReportFilters(period_from=(2025, 1)))


class TypoDoesNotPassSilentlyTest(unittest.TestCase):
    """То, ради чего пункт и заведён.

    Со словарём опечатка в ключе не вызывала ошибки: отбор молча не применялся,
    и расхождение обнаруживалось разве что по цифрам в готовом отчёте.
    """

    def test_unknown_field_is_rejected_at_construction(self):
        with self.assertRaises(TypeError):
            ReportFilters(airlines_ids=(1,))

    def test_unknown_attribute_is_rejected_at_reading(self):
        misspelled = "airlne_ids"

        with self.assertRaises(AttributeError):
            getattr(ReportFilters(), misspelled)

    def test_filters_cannot_be_changed_in_passing(self):
        """Отбор едет через несколько слоёв; менять его по дороге никто не должен."""
        with self.assertRaises(FrozenInstanceError):
            ReportFilters().airline_ids = (1,)


class NarrowingKeepsTheRestTest(unittest.TestCase):
    """Свод по одному предприятию сужает уже собранный отбор, а не собирает заново."""

    def test_airline_narrowing_keeps_period_and_indicators(self):
        base = ReportFilters(indicator_ids=(1, 2), period_from=(2025, 1), period_to=(2025, 3))

        narrowed = with_airline(base, 7)

        self.assertEqual((7,), narrowed.airline_ids)
        self.assertEqual((1, 2), narrowed.indicator_ids)
        self.assertEqual(((2025, 1), (2025, 3)), narrowed.period)

    def test_airport_narrowing_replaces_the_previous_choice(self):
        narrowed = with_airport(ReportFilters(airport_ids=(1, 2)), 3)

        self.assertEqual((3,), narrowed.airport_ids)

    def test_original_is_left_alone(self):
        base = ReportFilters(airline_ids=(1, 2))

        with_airline(base, 7)

        self.assertEqual((1, 2), base.airline_ids)


class FakeFilterWidget:
    """Виджет фильтров в том виде, в каком его читает контроллер."""

    def __init__(self, mode=MODE_AIRLINE, airlines=None, airports=None,
                 indicators=None, routes=None, layout=None, period=True):
        self.current_mode = mode
        self._airlines = airlines
        self._airports = airports
        self._indicators = indicators
        self._routes = routes
        self._layout = layout
        self._period = period

    def get_airline_filter_ids(self):
        return self._airlines

    def get_airport_filter_ids(self):
        return self._airports

    def get_indicator_filter_ids(self):
        return self._indicators

    def get_route_filter_types(self):
        return self._routes

    def get_pivot_table_layout(self):
        return self._layout

    def get_from_month(self):
        return "January" if self._period else None

    def get_from_year(self):
        return 2025 if self._period else None

    def get_to_month(self):
        return "March" if self._period else None

    def get_to_year(self):
        return 2025 if self._period else None


class ControllerBuildsTypedFiltersTest(unittest.TestCase):
    """Производитель отбора отдаёт объект, а не словарь."""

    def setUp(self):
        self.controller = FilterController()

    def test_airline_tab_collects_everything(self):
        widget = FakeFilterWidget(
            airlines=[7], indicators=[1, 2], routes=["trunk"], layout="summary"
        )

        filters = self.controller.get_current_filters(widget)

        self.assertIsInstance(filters, ReportFilters)
        self.assertEqual((7,), filters.airline_ids)
        self.assertEqual((1, 2), filters.indicator_ids)
        self.assertEqual(("trunk",), filters.route_types)
        self.assertEqual("summary", filters.pivot_table_layout)
        self.assertEqual(((2025, 1), (2025, 3)), filters.period)

    def test_airline_tab_leaves_airports_empty(self):
        filters = self.controller.get_current_filters(FakeFilterWidget(airlines=[7]))

        self.assertEqual((), filters.airport_ids)

    def test_airport_tab_collects_its_own(self):
        widget = FakeFilterWidget(mode=MODE_AIRPORT, airports=[3], indicators=[1])

        filters = self.controller.get_current_filters(widget)

        self.assertEqual((3,), filters.airport_ids)
        self.assertEqual((), filters.airline_ids)
        self.assertEqual((), filters.route_types)

    def test_airport_tab_widget_gives_one_airport(self):
        class AirportTabWidget(FakeFilterWidget):
            def get_airport_id(self):
                return 3

        filters = self.controller.get_airport_tab_filters(
            AirportTabWidget(mode=MODE_AIRPORT, indicators=[1])
        )

        self.assertEqual((3,), filters.airport_ids)
        self.assertEqual(3, filters.airport_id)
        self.assertEqual(3, filters.entity_id)

    def test_nothing_chosen_gives_an_empty_selection(self):
        filters = self.controller.get_current_filters(FakeFilterWidget(period=False))

        self.assertFalse(filters)
        self.assertEqual(NO_FILTERS, filters)


if __name__ == "__main__":
    unittest.main()
