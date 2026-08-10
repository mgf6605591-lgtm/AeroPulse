"""Колонка «Всего»: местные и субсидируемые не считаются дважды (BUG-2).

В бланке 12-ГА виды сообщения вложены. Графа 6 — «Внутренние — всего», графы 7 и 8
подписаны «из них» и являются её частью, а итоговая графа 9 складывает только
графы 4, 5 и 6. Свод же перебирал все четыре вида подряд, поэтому местные и
субсидируемые попадали в итог и отдельно, и в составе внутренних.

Дефект не проявлялся при фильтре по одному виду маршрута — там лишние ключи
отсекались SQL-фильтром и давали нули, — а срабатывал ровно в режиме по
умолчанию, когда фильтра нет и показаны все виды сразу.

Числа взяты из настоящего бланка: строка 1 «Самолето-километры» за январь 2025 —
графы 0, 0, 452, 33.95, и собственная итоговая графа бланка равна 452.
"""

import unittest

from controllers.reports.ga12_pivot import _route_type_keys_for_total_sum
from controllers.report_filters import ReportFilters
from tests.support import FakeRecord, PivotCase

# Строка 1 бланка: международные (гр. 4 и 5), внутренние всего (гр. 6),
# из них местные (гр. 7). Графа 9 бланка — ИТОГО гр.4+гр.5+гр.6.
BLANK_TRUNK = 0
BLANK_LOCAL = 452
BLANK_INTERREGIONAL = 33.95
BLANK_TOTAL = 452


def blank_row_records(month="January", year=2025, airline=("Тестовая АК", 1)):
    """Строка 1 бланка в виде записей отчётности."""
    return [
        FakeRecord("965", "Самолето-километры", month, year, BLANK_TRUNK,
                   route_type="trunk", airline=airline),
        FakeRecord("965", "Самолето-километры", month, year, BLANK_LOCAL,
                   route_type="local", airline=airline),
        FakeRecord("965", "Самолето-километры", month, year, BLANK_INTERREGIONAL,
                   route_type="interregional", airline=airline),
    ]


class TotalKeysTest(unittest.TestCase):
    """Какие виды сообщения входят в итог."""

    def test_all_four_reduce_to_the_blank_total(self):
        """Показаны все виды — в итоге остаются графы 4+5+6."""
        self.assertEqual(
            {"trunk", "local"},
            _route_type_keys_for_total_sum(["trunk", "local", "interregional", "subsidir"]),
        )

    def test_nested_type_alone_is_summed_by_itself(self):
        """Родителя в выборке нет — удваивать нечего."""
        self.assertEqual({"interregional"}, _route_type_keys_for_total_sum(["interregional"]))
        self.assertEqual({"subsidir"}, _route_type_keys_for_total_sum(["subsidir"]))

    def test_parent_absorbs_its_children(self):
        self.assertEqual({"local"}, _route_type_keys_for_total_sum(["local", "interregional"]))
        self.assertEqual(
            {"local"}, _route_type_keys_for_total_sum(["local", "interregional", "subsidir"])
        )

    def test_independent_types_are_kept(self):
        self.assertEqual({"trunk", "local"}, _route_type_keys_for_total_sum(["trunk", "local"]))


class PivotTotalsTest(PivotCase):
    """Итог во всех построителях свода 12-ГА."""

    def setUp(self):
        super().setUp()
        self.records = blank_row_records()

    def test_per_airline_by_routes(self):
        """Прежде здесь было 485.95 — внутренние плюс входящие в них местные."""
        result = self.build_per_airline_by_routes(self.records)
        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_TOTAL, row["m_2025_January_total"])

    def test_columns_themselves_are_unchanged(self):
        """Сами графы показываются как есть — свёрнут только итог."""
        result = self.build_per_airline_by_routes(self.records)
        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_LOCAL, row["m_2025_January_rt_local"])
        self.assertEqual(BLANK_INTERREGIONAL, row["m_2025_January_rt_interregional"])

    def test_all_airlines_summary_column(self):
        result = self.build_all_airlines(self.records)
        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_TOTAL, row["m_2025_January_total"])

    def test_per_airline_summary_layout(self):
        result = self.build_per_airline_summary(self.records)
        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_TOTAL, row["m_2025_January"])

    def test_multi_airline_by_routes(self):
        result = self.build_multi_airline_by_routes(self.records)
        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_TOTAL, row["m_2025_January_aid_1_total"])

    def test_two_airlines_are_added_up(self):
        """Свод по нескольким АК: удвоения нет ни внутри АК, ни между ними."""
        records = blank_row_records() + blank_row_records(airline=("Вторая АК", 2))

        result = self.build_all_airlines(records)

        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_TOTAL * 2, row["m_2025_January_total"])


class HeaderWordingTest(PivotCase):
    """Подписи колонок повторяют шапку бланка.

    Короткие «Внутренние», «Местные», «Субсидируемые» скрывали вложенность граф:
    итог по ним не складывается, и без слов «из них» верная цифра выглядела бы
    ошибкой — колонка «Всего» меньше суммы соседних.
    """

    def test_route_columns_follow_the_blank(self):
        result = self.build_per_airline_by_routes(blank_row_records())

        self.assertIn("Внутренние — всего", result["headers"])
        self.assertIn("из них местные", result["headers"])
        self.assertIn("из них субсидируемые", result["headers"])

    def test_total_column_is_named_as_in_the_blank(self):
        result = self.build_per_airline_by_routes(blank_row_records())

        self.assertIn("ИТОГО", result["headers"])
        self.assertNotIn("Всего", result["headers"])

    def test_multi_airline_headers_name_the_airline(self):
        result = self.build_multi_airline_by_routes(blank_row_records())

        self.assertIn("Тестовая АК — ИТОГО", result["headers"])

    def test_summary_layout_keeps_its_own_total(self):
        """Там «Всего» — сумма по месяцам, а не итог бланка: переименовывать нечего."""
        result = self.build_per_airline_summary(blank_row_records())

        self.assertIn("Всего", result["headers"])


class FilteredTotalsTest(PivotCase):
    """Фильтр по видам маршрута: итог считается по показанным графам."""

    def test_single_nested_type_keeps_its_own_value(self):
        """Раньше это работало случайно: лишние ключи отсекал SQL-фильтр."""
        records = [
            FakeRecord("965", "Самолето-километры", "January", 2025, BLANK_INTERREGIONAL,
                       route_type="interregional"),
        ]

        result = self.build_per_airline_by_routes(records, filters=ReportFilters(route_types=("interregional",)))

        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_INTERREGIONAL, row["m_2025_January_total"])

    def test_parent_and_child_together_count_once(self):
        records = [
            FakeRecord("965", "Самолето-километры", "January", 2025, BLANK_LOCAL,
                       route_type="local"),
            FakeRecord("965", "Самолето-километры", "January", 2025, BLANK_INTERREGIONAL,
                       route_type="interregional"),
        ]

        result = self.build_per_airline_by_routes(
            records, filters=ReportFilters(route_types=("local", "interregional"))
        )

        row = self.row_for_code(result, "965")
        self.assertEqual(BLANK_LOCAL, row["m_2025_January_total"])


if __name__ == "__main__":
    unittest.main()
