"""Сводный бланк 15-ГА и сводка по всем аэропортам.

Три вещи, которые нечем было проверить и в которых легко разойтись с бланком:

* **раскладка граф сводного бланка** — между графами пассажиров вставлены «в т.ч.
  РБ», и сдвиг на одну графу увёл бы принятых пассажиров в отправленных;
* **колонки сводки** — квартал и нарастающий итог складываются только из полных
  наборов месяцев, иначе неполный квартал выглядел бы кварталом;
* **«Итого»** — сводный блок предприятия равен сумме его аэропортов, и сложение
  всех показанных строк подряд удвоило бы итог.

Фикстура бланка собрана по самому бланку (`tests/support.py`), а не по таблицам
парсера: фикстура, выведенная из разбираемого кода, подтверждает только себя.
"""

import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from controllers.reports import ga15_summary
from controllers.report_filters import ReportFilters
from db.models.entities import Airport, AirportIndicators, Indicator, Locality
from importers.data_importer import DataImporter
from parsers.f15_fkp_xlsx_parser import F15FKPXLSXParser
from tests.support import (
    GA15_ENTERPRISE_GRAPHS,
    GA15_ENTERPRISE_NAME,
    MigratedDbCase,
    ga15_enterprise_cell,
    make_ga15_enterprise_workbook,
)
from utils.entity_codes import CODE_LENGTH, transliterate, unique_entity_code
from utils.ga15_airport_layout import GA15_FILTERED_OUT, GA15_METRIC_TAGS
from utils.ga15_summary_layout import (
    GA15_SUMMARY_ENTITY_KEY,
    GA15_SUMMARY_METRIC_HEADERS,
    GA15_SUMMARY_TOTAL_TITLE,
    summary_columns,
    summary_period_blocks,
)


def full_year(year: int = 2025):
    return [(year, month) for month in range(1, 13)]


class AirportCodeTest(unittest.TestCase):
    """Код заводимой записи: бланк его не называет, а колонка обязательна."""

    def test_name_becomes_latin_capitals(self):
        self.assertEqual("ALDAN", transliterate("Алдан"))

    def test_multi_letter_replacements_are_spelled_out(self):
        self.assertEqual("SCHUCHE", transliterate("Щучье"))

    def test_code_never_outgrows_the_column(self):
        code = unique_entity_code("Верхневилюйск", set())

        self.assertLessEqual(len(code), CODE_LENGTH)

    def test_collision_is_resolved_by_a_number(self):
        taken = {unique_entity_code("Алдан", set())}

        second = unique_entity_code("Алданский", taken)

        self.assertNotIn(second, taken)
        self.assertLessEqual(len(second), CODE_LENGTH)

    def test_a_long_run_of_collisions_still_ends(self):
        taken = set()
        for _ in range(30):
            taken.add(unique_entity_code("Алдан", taken))

        self.assertEqual(30, len(taken))

    def test_a_name_without_letters_still_gets_a_code(self):
        self.assertTrue(unique_entity_code("—", set()))


class SummaryPeriodBlocksTest(unittest.TestCase):
    """Колонки сводки: месяцы, кварталы и нарастающие итоги — как в самой сводке."""

    def labels(self, months):
        return [block.label for block in summary_period_blocks(months)]

    def test_full_year_repeats_the_summary_sheet(self):
        self.assertEqual(
            [
                "Январь 2025", "Февраль 2025", "Март 2025", "1 квартал 2025",
                "Апрель 2025", "Май 2025", "Июнь 2025", "2 квартал 2025",
                "6 месяцев 2025",
                "Июль 2025", "Август 2025", "Сентябрь 2025", "3 квартал 2025",
                "9 месяцев 2025",
                "Октябрь 2025", "Ноябрь 2025", "Декабрь 2025", "4 квартал 2025",
                "12 месяцев 2025",
            ],
            self.labels(full_year()),
        )

    def test_an_incomplete_quarter_is_not_shown(self):
        """Сумма двух месяцев из трёх называлась бы кварталом и занижала бы отчёт."""
        self.assertEqual(["Февраль 2025", "Март 2025"], self.labels([(2025, 2), (2025, 3)]))

    def test_a_quarter_appears_once_its_months_are_all_there(self):
        self.assertIn("1 квартал 2025", self.labels([(2025, m) for m in (1, 2, 3)]))

    def test_cumulative_totals_count_from_january(self):
        """Полугодие без первого квартала — не полугодие."""
        labels = self.labels([(2025, m) for m in range(4, 13)])

        self.assertIn("2 квартал 2025", labels)
        self.assertNotIn("6 месяцев 2025", labels)
        self.assertNotIn("12 месяцев 2025", labels)

    def test_each_year_gets_its_own_blocks(self):
        labels = self.labels(full_year(2024) + full_year(2025))

        self.assertIn("12 месяцев 2024", labels)
        self.assertIn("12 месяцев 2025", labels)

    def test_quarter_sums_its_three_months(self):
        quarter = next(
            block for block in summary_period_blocks(full_year())
            if block.label == "1 квартал 2025"
        )

        self.assertEqual(((2025, 1), (2025, 2), (2025, 3)), quarter.months)

    def test_columns_are_eleven_per_period_plus_the_name(self):
        blocks = summary_period_blocks(full_year())

        headers, keys, groups = summary_columns(blocks, GA15_METRIC_TAGS)

        self.assertEqual(1 + len(blocks) * len(GA15_SUMMARY_METRIC_HEADERS), len(headers))
        self.assertEqual(len(headers), len(keys))
        self.assertEqual(len(blocks), len(groups))
        self.assertTrue(all(last - first == 10 for first, last, _ in groups))

    def test_the_year_is_always_named(self):
        """Колонка «Январь» без года не читается вне того сеанса, где её сделали."""
        for label in self.labels(full_year()):
            self.assertIn("2025", label)


class EnterpriseBlankCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "15-ГА.xlsx")
        make_ga15_enterprise_workbook(self.path)

    def parsed(self):
        return F15FKPXLSXParser.parse_file(self.path)

    def block(self, name: str):
        for block in self.parsed()["airports"]:
            if block["name"] == name:
                return block
        raise AssertionError(f"в разборе нет блока «{name}»")

    @staticmethod
    def value(block, code: str):
        for row in block["indicators"]:
            if row["indicator_code"] == code:
                return row["value"]
        raise AssertionError(f"в блоке нет показателя {code}")


class EnterpriseBlankParsingTest(EnterpriseBlankCase):
    """Разбор сводного бланка: блоки, их состав и раскладка граф."""

    def test_the_workbook_is_recognised(self):
        self.assertTrue(F15FKPXLSXParser.is_fkp_workbook(self.path))

    def test_the_enterprise_comes_first_and_the_airports_follow(self):
        names = [block["name"] for block in self.parsed()["airports"]]

        self.assertEqual([GA15_ENTERPRISE_NAME, "Алдан", "Батагай"], names)

    def test_the_enterprise_belongs_to_nobody(self):
        self.assertIsNone(self.block(GA15_ENTERPRISE_NAME)["parent_name"])

    def test_every_airport_names_its_enterprise(self):
        for name in ("Алдан", "Батагай"):
            self.assertEqual(GA15_ENTERPRISE_NAME, self.block(name)["parent_name"], name)

    def test_the_period_is_read_from_the_sheet(self):
        parsed = self.parsed()

        self.assertEqual("January", parsed["month"])
        self.assertEqual(2025, parsed["year"])

    def test_graphs_do_not_slip(self):
        """Между графами пассажиров стоят «в т.ч. РБ»: сдвиг на одну увёл бы данные."""
        block = self.block("Алдан")

        for graph, tag in GA15_ENTERPRISE_GRAPHS.items():
            self.assertEqual(
                Decimal(ga15_enterprise_cell(1, 1, graph)),
                self.value(block, f"15ГА-R05-{tag}"),
                f"графа {graph}",
            )

    def test_the_second_line_goes_to_its_own_row(self):
        block = self.block("Батагай")

        self.assertEqual(
            Decimal(ga15_enterprise_cell(2, 2, 3)),
            self.value(block, "15ГА-R06-ПАС_ОТП"),
        )

    def test_the_total_line_fills_both_rows_of_the_standard_blank(self):
        """Международных перевозок в бланке нет: строка 07 совпадает со строкой 08."""
        block = self.block("Алдан")
        expected = sum(ga15_enterprise_cell(1, line, 2) for line in (1, 2))

        self.assertEqual(Decimal(expected), self.value(block, "15ГА-R07-ВС"))
        self.assertEqual(Decimal(expected), self.value(block, "15ГА-R08-ВС"))

    def test_the_enterprise_block_is_the_sum_of_its_airports(self):
        """Так устроен присланный бланк — на этом и держится «Итого» сводки."""
        for tag in GA15_METRIC_TAGS:
            code = f"15ГА-R08-{tag}"
            airports = sum(
                self.value(self.block(name), code) for name in ("Алдан", "Батагай")
            )
            self.assertEqual(airports, self.value(self.block(GA15_ENTERPRISE_NAME), code), tag)


class EnterpriseImportTest(MigratedDbCase):
    """Один файл — отчётность всех аэропортов предприятия."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "15-ГА.xlsx")
        make_ga15_enterprise_workbook(self.path)

    def do_import(self, path=None) -> dict:
        data = F15FKPXLSXParser.parse_file(path or self.path)
        data["source_file"] = "15-ГА.xlsx"
        with self.Session() as session:
            return DataImporter._import_airport_data(session, data)

    def airports(self) -> dict:
        with self.Session() as session:
            return {ap.name: ap for ap in session.query(Airport).all()}

    def test_import_succeeds(self):
        self.assertTrue(self.do_import()["success"])

    def test_every_block_becomes_an_airport(self):
        self.do_import()

        self.assertEqual(
            {GA15_ENTERPRISE_NAME, "Алдан", "Батагай"}, set(self.airports())
        )

    def test_created_airports_are_named_in_the_report(self):
        """Импорт пополняет справочник — узнавать об этом задним числом нельзя."""
        result = self.do_import()

        self.assertEqual(
            {GA15_ENTERPRISE_NAME, "Алдан", "Батагай"}, set(result["created_entities"])
        )
        self.assertIn("Алдан", result["message"])

    def test_airports_point_at_their_enterprise(self):
        self.do_import()

        airports = self.airports()
        enterprise = airports[GA15_ENTERPRISE_NAME]
        self.assertIsNone(enterprise.parent_id)
        for name in ("Алдан", "Батагай"):
            self.assertEqual(enterprise.id, airports[name].parent_id, name)

    def test_created_codes_are_unique(self):
        self.do_import()

        codes = [ap.code for ap in self.airports().values()]
        self.assertEqual(len(codes), len(set(codes)))

    def test_values_land_under_their_own_airport(self):
        self.do_import()

        with self.Session() as session:
            row = (
                session.query(AirportIndicators)
                .join(Indicator, AirportIndicators.indicator_id == Indicator.id)
                .join(Airport, AirportIndicators.airport_id == Airport.id)
                .filter(Airport.name == "Батагай", Indicator.code == "15ГА-R05-ВС")
                .one()
            )
        self.assertEqual(Decimal(ga15_enterprise_cell(2, 1, 2)), row.value)

    def test_reimport_does_not_double_the_reference(self):
        self.do_import()

        self.do_import()

        self.assertEqual(3, len(self.airports()))
        with self.Session() as session:
            self.assertEqual(3, session.query(Locality).count())

    def test_reimport_updates_instead_of_adding(self):
        first = self.do_import()

        second = self.do_import()

        self.assertEqual(0, second["imported"])
        self.assertEqual(first["imported"], second["updated"])

    def test_a_file_without_values_leaves_the_reference_alone(self):
        """Отказ не должен оставлять в справочнике записи из непринятого файла."""
        empty = os.path.join(os.path.dirname(self.path), "пустой.xlsx")
        make_ga15_enterprise_workbook(empty, airports=("Алдан",))
        data = F15FKPXLSXParser.parse_file(empty)
        for block in data["airports"]:
            block["indicators"] = []

        with self.Session() as session:
            result = DataImporter._import_airport_data(session, data)

        self.assertFalse(result["success"])
        self.assertEqual({}, self.airports())


class FakeAirportAggregateRow:
    """Строка агрегата 15-ГА со всеми полями, по которым группирует база."""

    def __init__(self, airport_id: int, indicator_code: str, month: str, total,
                 year: int = 2025, records: int = 1):
        self.airport_id = airport_id
        self.indicator_code = indicator_code
        self.month = month
        self.year = year
        self.total = total
        self.records = records


class Ga15SummaryPivotTest(MigratedDbCase):
    """Сводка по всем аэропортам: порядок строк, «Итого» и отбор."""

    ENTERPRISE, CHILD, ALONE = 1, 2, 3

    def setUp(self):
        super().setUp()
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with Session() as session:
            session.add(Locality(id=1, name="Город"))
            session.add(Airport(id=self.ENTERPRISE, code="FKP", name="ФКП", locality_id=1))
            session.add(
                Airport(id=self.CHILD, code="ALDAN", name="Алдан", locality_id=1,
                        parent_id=self.ENTERPRISE)
            )
            session.add(Airport(id=self.ALONE, code="YKS", name="Якутск", locality_id=1))
            for number, tag in enumerate(GA15_METRIC_TAGS, start=1):
                code = f"15ГА-R08-{tag}"
                session.add(Indicator(id=number, name=code, code=code, measure="ед."))
            session.commit()
        self.id_by_tag = {tag: n for n, tag in enumerate(GA15_METRIC_TAGS, start=1)}

        session_patch = patch("controllers.reports.ga15_summary.get_session", Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)

    def build(self, rows=(), **filters):
        base = {"period_from": (2025, 1), "period_to": (2025, 3)}
        base.update(filters)
        with patch("controllers.airport_ind_service.AirportIndicatorService.aggregate",
                   return_value=list(rows)):
            return ga15_summary.build(ReportFilters(**base))

    @staticmethod
    def titles(result):
        return [row[GA15_SUMMARY_ENTITY_KEY] for row in result["rows"]]

    @staticmethod
    def row(result, title: str):
        for row in result["rows"]:
            if row[GA15_SUMMARY_ENTITY_KEY].strip() == title:
                return row
        raise AssertionError(f"в сводке нет строки «{title}»")

    def aircraft(self, tag="ВС", **kwargs):
        return FakeAirportAggregateRow(indicator_code=f"15ГА-R08-{tag}", **kwargs)

    # --- строки -------------------------------------------------------------

    def test_all_airports_are_shown_without_any_filter(self):
        titles = [title.strip() for title in self.titles(self.build())]

        self.assertEqual(["ФКП", "Алдан", "Якутск", GA15_SUMMARY_TOTAL_TITLE], titles)

    def test_the_breakdown_stands_under_its_enterprise(self):
        titles = self.titles(self.build())

        self.assertTrue(titles[1].startswith(" "), titles[1])
        self.assertFalse(titles[0].startswith(" "), titles[0])

    def test_a_chosen_airport_narrows_the_rows(self):
        result = self.build(airport_ids=(self.ALONE,))

        self.assertEqual(["Якутск", GA15_SUMMARY_TOTAL_TITLE],
                         [t.strip() for t in self.titles(result)])

    def test_a_chosen_child_stands_on_its_own(self):
        """Без своего предприятия аэропорт входит в итог сам, иначе итог был бы нулём."""
        rows = [self.aircraft(airport_id=self.CHILD, month="January", total=7)]

        result = self.build(rows, airport_ids=(self.CHILD,))

        self.assertEqual(7.0, self.row(result, GA15_SUMMARY_TOTAL_TITLE)["m2025_1_ВС"])

    # --- «Итого» ------------------------------------------------------------

    def test_total_adds_up_the_enterprises_only(self):
        """Сводный блок предприятия и есть сумма его аэропортов (BUG сложения дважды)."""
        rows = [
            self.aircraft(airport_id=self.ENTERPRISE, month="January", total=10),
            self.aircraft(airport_id=self.CHILD, month="January", total=10),
            self.aircraft(airport_id=self.ALONE, month="January", total=5),
        ]

        result = self.build(rows)

        self.assertEqual(15.0, self.row(result, GA15_SUMMARY_TOTAL_TITLE)["m2025_1_ВС"])

    def test_the_enterprise_keeps_its_own_figures(self):
        rows = [self.aircraft(airport_id=self.ENTERPRISE, month="January", total=10)]

        result = self.build(rows)

        self.assertEqual(10.0, self.row(result, "ФКП")["m2025_1_ВС"])

    # --- периоды ------------------------------------------------------------

    def test_a_month_without_data_is_a_zero_not_a_missing_column(self):
        rows = [self.aircraft(airport_id=self.ALONE, month="January", total=4)]

        result = self.build(rows)

        self.assertEqual(0.0, self.row(result, "Якутск")["m2025_2_ВС"])
        self.assertEqual(4.0, self.row(result, "Якутск")["q2025_1_ВС"])

    def test_the_quarter_sums_its_months(self):
        rows = [
            self.aircraft(airport_id=self.ALONE, month=month, total=2)
            for month in ("January", "February", "March")
        ]

        result = self.build(rows)

        self.assertEqual(6.0, self.row(result, "Якутск")["q2025_1_ВС"])

    def test_columns_follow_the_period_not_the_data(self):
        """Один месяц с цифрами не должен схлопывать квартал до одной колонки."""
        rows = [self.aircraft(airport_id=self.ALONE, month="January", total=1)]

        result = self.build(rows)

        self.assertEqual(
            ["Январь 2025", "Февраль 2025", "Март 2025", "1 квартал 2025"],
            [label for _, _, label in result["groups"]],
        )

    # --- отбор показателей --------------------------------------------------

    def test_a_graph_outside_the_filter_is_marked_not_zeroed(self):
        """Нулём отфильтрованную сводку было бы не отличить от пустой (FUNC-7)."""
        rows = [self.aircraft(airport_id=self.ALONE, month="January", total=3)]

        result = self.build(rows, indicator_ids=(self.id_by_tag["ВС"],))
        row = self.row(result, "Якутск")

        self.assertEqual(3.0, row["m2025_1_ВС"])
        self.assertEqual(GA15_FILTERED_OUT, row["m2025_1_ПАС_ОТП"])

    def test_the_counter_names_the_kept_graphs(self):
        result = self.build(indicator_ids=(self.id_by_tag["ВС"],))

        self.assertEqual(1, result["stats"]["indicators"])

    # --- пустой справочник --------------------------------------------------

    def test_an_empty_reference_says_so(self):
        result = self.build(airport_ids=(999,))

        self.assertIn("нет аэропортов", result["rows"][0][GA15_SUMMARY_ENTITY_KEY])


if __name__ == "__main__":
    unittest.main()
