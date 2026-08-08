"""Три низких пункта: повторный разбор XML, ненайденная разметка, фильтр 15-ГА
(BUG-17, BUG-18, FUNC-7).

Пункты из разных мест программы, но проверяются одинаково — по наблюдаемому
следствию, а не по устройству правки: сколько раз файл разбирается, что видит
пользователь вместо трейсбека и какие строки бланка остаются на экране.
"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy.orm import sessionmaker

from controllers.report_filters import ReportFilters
from db.models.entities import Airport, Indicator, Locality
from parsers.xml_parser import XMLParser
from services.parse_service import ParseService
from tests.support import MigratedDbCase
from utils.ga15_airport_layout import (
    GA15_FILTERED_OUT,
    GA15_KEYS,
    GA15_METRIC_TAGS,
    GA15_NOT_FILLED,
    GA15_TABLE_ROWS,
)

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


def make_ga12_xml(path: str) -> str:
    """Небольшая выгрузка 12-ГА: пары строк бланка достаточно для сверки."""
    root = ET.Element("report", {"year": "2025", "period": "01"})
    title = ET.SubElement(root, "title")
    ET.SubElement(title, "item", {"name": "name", "value": "Тестовая АК"})
    section = ET.SubElement(ET.SubElement(root, "sections"), "section")

    for xml_row, value in ((2, "100"), (4, "200")):
        node = ET.SubElement(section, "row", {"code": str(xml_row)})
        for col in range(4, 9):
            ET.SubElement(node, "col", {"code": str(col)}).text = value

    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


class XmlIsParsedOnceTest(unittest.TestCase):
    """BUG-17: службе нужен корень, чтобы определить форму, — и она его уже имеет.

    Для 15-ГА разобранный корень передавался дальше с самого начала, а для 12-ГА
    парсер читал и разбирал тот же файл заново.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = make_ga12_xml(os.path.join(tmp.name, "report.xml"))

    def parse_calls(self, run):
        """Сколько раз разбирается XML за один вызов.

        Считается на самом `xml.etree.ElementTree`: и служба, и оба парсера
        обращаются к одному и тому же модулю.
        """
        with patch("xml.etree.ElementTree.parse", wraps=ET.parse) as parse:
            result = run()
        return result, parse.call_count

    def test_service_parses_the_file_once(self):
        _, calls = self.parse_calls(
            lambda: ParseService.parse_file(self.path, entity_type="airline", entity_id=1)
        )

        self.assertEqual(1, calls)

    def test_result_is_the_same_as_parsing_the_file_directly(self):
        """Разбор корня и разбор файла обязаны давать одно и то же."""
        through_service = ParseService.parse_file(
            self.path, entity_type="airline", entity_id=1
        )
        through_parser = XMLParser.parse_file(
            self.path, entity_type="airline", entity_id=1
        )

        self.assertEqual(through_parser, through_service)

    def test_direct_parser_call_still_works(self):
        """`parse_file` остаётся точкой входа для тех, у кого есть только имя файла."""
        result, calls = self.parse_calls(lambda: XMLParser.parse_file(self.path))

        self.assertEqual(1, calls)
        self.assertTrue(result["indicators"])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class MissingMarkupIsExplainedTest(unittest.TestCase):
    """BUG-18: разметка ищется в трёх местах, и её может не быть ни в одном.

    Возвращался первый кандидат — заведомо несуществующий путь, — и падал уже
    `uic.loadUi` сообщением о неразобранном документе. Для сборки PyInstaller
    это типичный сбой, и по такому сообщению не понять, чего не хватает.
    """

    def test_path_is_found_when_the_file_is_in_place(self):
        from forms.auth import Auth

        self.assertTrue(Auth._resolve_auth_ui_path().exists())

    def test_refusal_names_every_checked_path(self):
        from forms.auth import Auth

        with patch.object(Path, "exists", return_value=False):
            with self.assertRaises(FileNotFoundError) as failure:
                Auth._resolve_auth_ui_path()

        text = str(failure.exception)
        listed = [line for line in text.splitlines() if line.strip().endswith("auth.ui")]
        self.assertIn("auth.ui", text)
        self.assertEqual(3, len(listed), text)

    def test_window_refuses_before_uic_sees_the_path(self):
        """Отказ приходит из поиска пути, а не из разбора несуществующего файла."""
        from forms.auth import Auth

        with patch.object(Path, "exists", return_value=False):
            with patch("forms.auth.uic.loadUi") as load:
                with self.assertRaises(FileNotFoundError):
                    Auth()

        load.assert_not_called()


class StartupFailureIsShownTest(unittest.TestCase):
    """BUG-18: без окна сообщения запуск выглядит как «ярлык нажат, ничего нет».

    Та же причина, по которой окно создаётся раньше базы (BUG-15): в собранном
    приложении трейсбек уходит в несуществующий stdout.
    """

    def run_main(self, failure):
        import main

        with patch.object(main, "setup_logging", return_value=Path("/tmp/aeropulse.log")), \
             patch.object(main, "init_db"), \
             patch.object(main, "ensure_initial_admin", return_value=True), \
             patch.object(main, "QApplication"), \
             patch.object(main, "QMessageBox") as message_box, \
             patch.object(main, "AppController") as controller_cls, \
             patch.object(main.os, "chdir"):
            controller_cls.return_value.start.side_effect = failure
            with self.assertRaises(SystemExit) as exit_code:
                main.main()
        return message_box, exit_code.exception.code

    def test_missing_markup_reaches_the_user(self):
        message_box, code = self.run_main(FileNotFoundError("не найден auth.ui"))

        self.assertEqual(1, code)
        message_box.critical.assert_called_once()

    def test_message_names_the_reason_and_the_log(self):
        message_box, _ = self.run_main(FileNotFoundError("не найден auth.ui"))

        text = message_box.critical.call_args.args[2]
        self.assertIn("не найден auth.ui", text)
        self.assertIn("окно входа", text)
        self.assertIn("aeropulse.log", text)

    def test_database_failure_still_names_the_database(self):
        """Сообщение стало общим на два отказа — второй не должен был потеряться."""
        import main

        with patch.object(main, "setup_logging", return_value=None), \
             patch.object(main, "init_db", side_effect=RuntimeError("база повреждена")), \
             patch.object(main, "QApplication"), \
             patch.object(main, "QMessageBox") as message_box, \
             patch.object(main.os, "chdir"):
            with self.assertRaises(SystemExit):
                main.main()

        text = message_box.critical.call_args.args[2]
        self.assertIn("базу данных", text)
        self.assertIn("база повреждена", text)


# Показатели бланка 15-ГА, заведённые в справочнике теста: строка × графа.
GA15_TEST_CODES = tuple(
    f"15ГА-{row_code}-{tag}"
    for row_code in ("R01", "R02", "R03", "R04ИНО", "R05", "R06", "R07", "R08", "R09")
    for tag in GA15_METRIC_TAGS
)


class FakeAirportAggregateRow:
    """Строка агрегата 15-ГА — то, что отдаёт база после GROUP BY."""

    def __init__(self, indicator_code: str, total, records: int = 1):
        self.indicator_code = indicator_code
        self.total = total
        self.records = records


class Ga15FilterHidesRowsTest(MigratedDbCase):
    """FUNC-7: фильтр показателей обнулял строки бланка вместо их скрытия.

    Свод собирался по полному макету, а фильтр ограничивал только выборку
    записей: невыбранная строка показывалась нулями, и отфильтрованный бланк
    было не отличить от бланка, где данных действительно нет.

    Показатель формы 15-ГА — это пересечение строки и графы
    (`15ГА-R05-ПАС_ОТП`), поэтому отбор решается по ячейке, а строка исчезает
    только тогда, когда из неё не выбрано ничего.
    """

    def setUp(self):
        super().setUp()
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with Session() as session:
            session.add(Locality(id=1, name="Город"))
            session.add(Airport(id=1, code="ЯКТ", name="Якутск", locality_id=1))
            for number, code in enumerate(GA15_TEST_CODES, start=1):
                session.add(Indicator(id=number, name=code, code=code, measure="ед."))
            # Показатель чужой формы: список фильтра общий на 12-ГА и 15-ГА.
            session.add(Indicator(id=900, name="Налет часов", code="356", measure="час."))
            session.commit()
        self.id_by_code = {code: n for n, code in enumerate(GA15_TEST_CODES, start=1)}

        session_patch = patch("controllers.data_controller.get_session", Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)

    def build(self, aggregate_rows=(), codes=None, indicator_ids=None):
        from controllers.data_controller import DataController

        if indicator_ids is None:
            indicator_ids = tuple(self.id_by_code[c] for c in (codes or ()))
        with patch("controllers.data_controller.AirportIndicatorService.aggregate",
                   return_value=list(aggregate_rows)):
            return DataController()._load_pivot_ga15_airport(
                ReportFilters(indicator_ids=tuple(indicator_ids)), airport_id=1
            )

    # --- чтение построенного свода -----------------------------------------

    @staticmethod
    def line_numbers(result):
        """Номера строк бланка, оставшиеся в своде."""
        return [
            str(row[GA15_KEYS[1]]) for row in result["rows"]
            if row.get(GA15_KEYS[1]) not in (None, "")
        ]

    @staticmethod
    def titles(result):
        return [row[GA15_KEYS[0]] for row in result["rows"] if row.get(GA15_KEYS[0])]

    @staticmethod
    def row_by_line(result, number: str):
        for row in result["rows"]:
            if str(row.get(GA15_KEYS[1])) == number:
                return row
        raise AssertionError(f"в своде нет строки {number}")

    @staticmethod
    def cell(row, tag):
        return row[GA15_KEYS[2 + GA15_METRIC_TAGS.index(tag)]]

    # --- полный бланк -------------------------------------------------------

    def test_without_a_filter_the_whole_blank_is_shown(self):
        result = self.build()

        expected = sum(
            1 for spec in GA15_TABLE_ROWS
            if spec.kind in ("data", "subdetail") and spec.row_code
        )
        self.assertEqual(expected, result["stats"]["indicators"])

    def test_without_a_filter_empty_cells_stay_zeros(self):
        """Отсутствие данных в заполняемой графе — по-прежнему ноль (BUG-30)."""
        row = self.row_by_line(self.build(), "5")

        self.assertEqual(0.0, self.cell(row, "ПАС_ОТП"))

    # --- отбор скрывает строки ---------------------------------------------

    def test_unselected_rows_disappear(self):
        result = self.build(codes=["15ГА-R05-ПАС_ОТП"])

        self.assertEqual(["5"], self.line_numbers(result))

    def test_unselected_rows_are_not_zeroed_out(self):
        """Ровно то, чем пункт и был: строка 01 оставалась в бланке нулями."""
        result = self.build(
            [FakeAirportAggregateRow("15ГА-R01-ПАС_ОТП", 77)],
            codes=["15ГА-R05-ПАС_ОТП"],
        )

        self.assertNotIn("1", self.line_numbers(result))

    def test_selected_row_keeps_its_value(self):
        result = self.build(
            [FakeAirportAggregateRow("15ГА-R05-ПАС_ОТП", 1234)],
            codes=["15ГА-R05-ПАС_ОТП"],
        )

        self.assertEqual(1234.0, self.cell(self.row_by_line(result, "5"), "ПАС_ОТП"))

    def test_row_survives_on_any_one_of_its_columns(self):
        """Строка исчезает, только когда из неё не выбрано ни одной графы."""
        result = self.build(codes=["15ГА-R05-ГР_ОТГР"])

        self.assertEqual(["5"], self.line_numbers(result))

    def test_statistics_count_the_shown_rows(self):
        result = self.build(codes=["15ГА-R05-ПАС_ОТП", "15ГА-R06-ПАС_ОТП"])

        self.assertEqual(2, result["stats"]["indicators"])

    # --- отбор гасит графы --------------------------------------------------

    def test_columns_outside_the_filter_are_dashed(self):
        row = self.row_by_line(self.build(codes=["15ГА-R05-ПАС_ОТП"]), "5")

        self.assertEqual(GA15_FILTERED_OUT, self.cell(row, "ПАС_ПРИН"))

    def test_selected_column_without_data_is_a_zero_not_a_dash(self):
        """Отличие «не выбрано» от «нет данных» — ради него метка и заведена."""
        row = self.row_by_line(self.build(codes=["15ГА-R05-ПАС_ОТП"]), "5")

        self.assertEqual(0.0, self.cell(row, "ПАС_ОТП"))

    def test_unfillable_columns_keep_the_blank_mark(self):
        """«Х» — свойство бланка и от фильтра не зависит (BUG-30)."""
        row = self.row_by_line(self.build(codes=["15ГА-R09-ВС"]), "9")

        self.assertEqual(GA15_NOT_FILLED, self.cell(row, "ПАС_ОТП"))
        self.assertEqual(0.0, self.cell(row, "ВС"))

    def test_a_row_of_only_unfillable_columns_disappears(self):
        """У строки 09 заполняется одно количество ВС: без него показывать нечего."""
        result = self.build(codes=["15ГА-R09-ПАС_ОТП"])

        self.assertNotIn("9", self.line_numbers(result))

    # --- заголовки ----------------------------------------------------------

    def test_subheading_goes_away_with_its_only_row(self):
        titles = self.titles(self.build(codes=["15ГА-R05-ПАС_ОТП"]))

        self.assertNotIn("в том числе:", titles)
        self.assertNotIn("иностранными авиакомпаниями", titles)

    def test_subheading_stays_when_its_row_is_selected(self):
        titles = self.titles(self.build(codes=["15ГА-R04ИНО-ПАС_ОТП"]))

        self.assertIn("в том числе:", titles)
        self.assertIn("иностранными авиакомпаниями", titles)

    def test_section_header_goes_away_with_all_of_its_rows(self):
        titles = self.titles(self.build(indicator_ids=(900,)))

        self.assertNotIn("Коммерческие перевозки", titles)

    def test_airport_and_period_stay_under_a_filter(self):
        """Шапка не зависит от отбора: без неё непонятно, чей это бланк."""
        titles = self.titles(self.build(codes=["15ГА-R05-ПАС_ОТП"]))

        self.assertTrue(any("Якутск" in title for title in titles), titles)
        self.assertTrue(any(title.startswith("за ") for title in titles), titles)

    def test_a_filter_without_ga15_rows_says_so(self):
        """Список фильтра общий на обе формы: в нём можно выбрать одну 12-ГА."""
        result = self.build(indicator_ids=(900,))

        self.assertEqual([], self.line_numbers(result))
        self.assertEqual(0, result["stats"]["indicators"])
        self.assertTrue(
            any("не входит в форму 15-ГА" in title for title in self.titles(result)),
            self.titles(result),
        )


if __name__ == "__main__":
    unittest.main()
