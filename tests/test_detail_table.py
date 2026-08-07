"""Подробная таблица: по строке видно, что именно удаляют (FUNC-11).

Регулярность — одно из двух измерений рейса: по ней бланк 12-ГА делится на
разделы, и вместе с типом маршрута она образует `Route`. В подробной таблице её
не показывали, поэтому две записи с одним показателем, месяцем и типом маршрута
выглядели одинаково. Удаляют записи именно из этого режима, отменить удаление
нечем (FUNC-6), журнала нет (FUNC-5).
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.constants import MODE_AIRLINE, MODE_AIRPORT

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DetailColumnsTest(unittest.TestCase):
    """Состав колонок подробного представления."""

    def setUp(self):
        from controllers.data_controller import DataController
        from tests.support import FakeRecord

        self.controller = DataController()
        # Две записи, отличающиеся только регулярностью, — тот самый случай.
        self.records = [
            FakeRecord("965", "Самолето-километры", "January", 2025, 100, regularity="regular"),
            FakeRecord("965н", "Самолето-километры", "January", 2025, 7, regularity="irregular"),
        ]

    def load(self, mode=MODE_AIRLINE):
        service = (
            "controllers.data_controller.AirlineIndicatorService.filter_indicators"
            if mode == MODE_AIRLINE
            else "controllers.data_controller.AirportIndicatorService.filter_indicators"
        )
        with patch(service, return_value=self.records):
            return self.controller.load_detail_data(mode, {"any": "filter"})

    def test_regularity_column_is_present(self):
        data = self.load()

        self.assertIn("Регулярность", data["headers"])
        self.assertIn("shipping.route.regularity", data["attrs"])

    def test_headers_and_attrs_stay_aligned(self):
        """Колонка и её атрибут сопоставляются по номеру — длины обязаны совпадать."""
        data = self.load()

        self.assertEqual(len(data["headers"]), len(data["attrs"]))

    def test_regularity_follows_the_route_type(self):
        """Обе колонки описывают рейс, поэтому стоят рядом."""
        data = self.load()

        self.assertEqual(
            data["headers"].index("Тип маршрута") + 1,
            data["headers"].index("Регулярность"),
        )

    def test_airport_view_has_no_regularity(self):
        """У аэропортов рейсов нет: 15-ГА не делится по регулярности."""
        data = self.load(MODE_AIRPORT)

        self.assertNotIn("Регулярность", data["headers"])
        self.assertEqual(len(data["headers"]), len(data["attrs"]))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DetailRowsAreDistinguishableTest(unittest.TestCase):
    """Строки, отличающиеся только регулярностью, различимы в таблице."""

    def setUp(self):
        from controllers.data_controller import DataController
        from db.models.sqlalchemy_table_model import SQLAlchemyTableModel
        from tests.support import FakeRecord

        records = [
            FakeRecord("965", "Самолето-километры", "January", 2025, 100, regularity="regular"),
            FakeRecord("965н", "Самолето-километры", "January", 2025, 7, regularity="irregular"),
        ]
        with patch(
            "controllers.data_controller.AirlineIndicatorService.filter_indicators",
            return_value=records,
        ):
            data = DataController().load_detail_data(MODE_AIRLINE, {"any": "filter"})

        self.model = SQLAlchemyTableModel()
        self.model.setHeaders(data["headers"])
        self.model.setColumnAttributes(data["attrs"])
        self.model.setData(data["records"])
        self.column = data["headers"].index("Регулярность")

    def row_text(self, row):
        return [
            self.model.data(self.model.index(row, c), Qt.ItemDataRole.DisplayRole)
            for c in range(self.model.columnCount())
        ]

    def test_regularity_is_shown_by_its_caption(self):
        self.assertEqual("Регулярные коммерческие", self.row_text(0)[self.column])
        self.assertEqual("Не регулярные коммерческие", self.row_text(1)[self.column])

    def test_rows_are_no_longer_identical(self):
        """Прежде строки различались только полем «Значение»."""
        first, second = self.row_text(0), self.row_text(1)

        self.assertNotEqual(first[self.column], second[self.column])


if __name__ == "__main__":
    unittest.main()
