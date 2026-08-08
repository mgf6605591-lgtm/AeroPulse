"""Неприменимые графы бланка 15-ГА и подсказка у нулевого значения (BUG-30, BUG-29).

В строке 09 «Все прочие операции» отсутствие данных выводилось как «Х» **во всех
одиннадцати графах**. В бланке «Х» означает другое — «показатель здесь не
заполняется», — и стоит она не везде: количество ВС в этой строке заполняется, а
«Х» напечатана в графах 4…13. Отсутствие данных в заполняемой графе — это ноль,
как во всех остальных строках (BUG-30).

Подсказка в подробной таблице собиралась под условием `if value`, которое считает
ложью и ноль, и `Decimal('0')`. Подсказка пропадала как раз у нулевых значений —
а ноль в отчётности не редкость, а норма (BUG-29).

Раскладка сверяется с настоящим бланком 15-ГА, который лежит в проекте: список
неприменимых граф взят из формы, а не выведен из общего правила.
"""

import os
import unittest

from controllers.report_filters import ReportFilters
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy.orm import sessionmaker

from db.models.entities import Airport, Locality
from tests.support import MigratedDbCase
from utils.ga15_airport_layout import (
    GA15_METRIC_TAGS,
    GA15_NOT_FILLED,
    GA15_TABLE_ROWS,
)

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Настоящий бланк 15-ГА, заполненный отчитывающейся организацией.
REAL_BLANK = PROJECT_ROOT / "ФКП АС 15-ГА Февраль 2026 год(1).xlsx"

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


def row_spec(row_code: str):
    for spec in GA15_TABLE_ROWS:
        if spec.row_code == row_code:
            return spec
    raise AssertionError(f"в раскладке нет строки {row_code}")


class NotFilledColumnsTest(unittest.TestCase):
    """Какие графы не заполняются — свойство строки бланка, а не строки кода."""

    def test_row_09_does_not_fill_columns_4_to_13(self):
        spec = row_spec("R09")

        self.assertEqual(set(GA15_METRIC_TAGS) - {"ВС"}, set(spec.not_filled))

    def test_aircraft_count_is_filled_in_row_09(self):
        """Прежде «Х» ставилась и сюда, хотя в графе должно стоять число."""
        self.assertNotIn("ВС", row_spec("R09").not_filled)

    def test_no_other_row_has_unfillable_columns(self):
        with_marks = [
            spec.row_code for spec in GA15_TABLE_ROWS
            if spec.row_code and spec.not_filled
        ]
        self.assertEqual(["R09"], with_marks)

    def test_mark_is_the_cyrillic_letter_from_the_blank(self):
        """Латинская «X» выглядит так же, а в бланке напечатана кириллическая."""
        self.assertEqual("Х", GA15_NOT_FILLED)


@unittest.skipUnless(REAL_BLANK.exists(), "настоящий бланк 15-ГА не приложен")
class LayoutMatchesTheRealBlankTest(unittest.TestCase):
    """Сверка с формой: перечень неприменимых граф не выдуман.

    Строка 09 в бланке — это строка листа, где во второй графе стоит 9. Графы
    3…13 листа отвечают одиннадцати меткам метрик в том же порядке.
    """

    @classmethod
    def setUpClass(cls):
        import pandas as pd

        cls.pd = pd
        sheet = pd.read_excel(REAL_BLANK, sheet_name="15-ГА", header=None)
        for _, row in sheet.iterrows():
            if str(row[1]).strip() == "9":
                cls.row09 = row
                return
        raise AssertionError("в бланке не нашлась строка 09")

    def marked_in_blank(self):
        """Метки метрик, у которых в бланке напечатана «Х»."""
        return {
            tag for column, tag in enumerate(GA15_METRIC_TAGS, start=2)
            if str(self.row09[column]).strip() == GA15_NOT_FILLED
        }

    def test_layout_marks_exactly_what_the_blank_marks(self):
        self.assertEqual(self.marked_in_blank(), set(row_spec("R09").not_filled))

    def test_blank_leaves_the_aircraft_column_empty_for_a_number(self):
        self.assertTrue(self.pd.isna(self.row09[2]))


class FakeAirportAggregateRow:
    """Строка агрегата 15-ГА — то, что отдаёт база после GROUP BY."""

    def __init__(self, indicator_code: str, total, records: int = 1):
        self.indicator_code = indicator_code
        self.total = total
        self.records = records


class Ga15PivotUsesTheLayoutTest(MigratedDbCase):
    """Связка: построитель свода должен брать неприменимые графы из раскладки.

    Без этой проверки правило жило бы в раскладке, а свод по-прежнему решал сам —
    ровно так пункт и появился: условие «строка R09» было вписано в построитель.
    """

    def setUp(self):
        super().setUp()
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with Session() as session:
            session.add(Locality(id=1, name="Город"))
            session.add(Airport(id=1, code="ЯКТ", name="Якутск", locality_id=1))
            session.commit()

        session_patch = patch("controllers.data_controller.get_session", Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)

    def build(self, aggregate_rows):
        from controllers.data_controller import DataController

        with patch("controllers.data_controller.AirportIndicatorService.aggregate",
                   return_value=aggregate_rows):
            return DataController()._load_pivot_ga15_airport(ReportFilters(), airport_id=1)

    def row09(self, result):
        for row in result["rows"]:
            if str(row.get("ga15_1")) == "9":
                return row
        raise AssertionError("в своде нет строки 09")

    def cell(self, row, tag):
        return row[f"ga15_{2 + GA15_METRIC_TAGS.index(tag)}"]

    def test_unfillable_columns_show_the_blank_mark(self):
        row = self.row09(self.build([]))

        for tag in set(GA15_METRIC_TAGS) - {"ВС"}:
            self.assertEqual(GA15_NOT_FILLED, self.cell(row, tag), tag)

    def test_missing_aircraft_count_is_a_zero_not_a_mark(self):
        """Прежде здесь стояла «Х»: данных нет — но графа-то заполняется."""
        row = self.row09(self.build([]))

        self.assertEqual(0.0, self.cell(row, "ВС"))

    def test_aircraft_count_is_shown_when_it_is_there(self):
        row = self.row09(self.build([FakeAirportAggregateRow("15ГА-R09-ВС", 42)]))

        self.assertEqual(42.0, self.cell(row, "ВС"))

    def test_other_rows_still_show_zero_for_missing_data(self):
        result = self.build([])
        internal = next(r for r in result["rows"] if str(r.get("ga15_1")) == "5")

        self.assertEqual(0.0, self.cell(internal, "ПАС_ОТП"))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class TooltipShowsZeroTest(unittest.TestCase):
    """BUG-29: подсказка пропадала у нулевого значения.

    Тот же приём, от которого прямо предостерегает комментарий в
    `data_controller`: «не использовать `if v` — `Decimal('0')` даёт False».
    """

    class Row:
        def __init__(self, value, name):
            self.value = value
            self.name = name

    def model_with(self, value, name="Тестовая АК"):
        from forms.models.sqlalchemy_table_model import SQLAlchemyTableModel

        model = SQLAlchemyTableModel()
        model.setHeaders(["Значение", "Авиакомпания"])
        model.setColumnAttributes(["value", "name"])
        model.set_source_data([self.Row(value, name)])
        self.addCleanup(model.deleteLater)
        return model

    def tooltip(self, model, col):
        return model.data(model.index(0, col), Qt.ItemDataRole.ToolTipRole)

    def test_zero_decimal_still_has_a_tooltip(self):
        model = self.model_with(Decimal("0"))

        self.assertEqual("Значение: 0", self.tooltip(model, 0))

    def test_zero_int_still_has_a_tooltip(self):
        model = self.model_with(0)

        self.assertEqual("Значение: 0", self.tooltip(model, 0))

    def test_non_zero_value_is_unchanged(self):
        model = self.model_with(Decimal("140.62"))

        self.assertEqual("Значение: 140.62", self.tooltip(model, 0))

    def test_empty_cell_has_no_tooltip(self):
        model = self.model_with(None)

        self.assertIsNone(self.tooltip(model, 0))

    def test_text_column_is_unaffected(self):
        model = self.model_with(Decimal("0"), name="Тестовая АК")

        self.assertEqual("Авиакомпания: Тестовая АК", self.tooltip(model, 1))


if __name__ == "__main__":
    unittest.main()
