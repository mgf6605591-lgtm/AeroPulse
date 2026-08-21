"""Закреплённая первая колонка свода: «Показатель» виден при прокрутке вбок.

В своде по маршрутам на трёх а/к за три месяца сорок пять колонок, и первым же
движением полосы прокрутки название строки уезжает за левый край: дальше на
экране одни числа, отнести их не к чему.

Закрепления колонок в `QTableView` нет, поэтому первая колонка показывается ещё
раз — накладкой поверх той же модели (`forms/widgets/frozen_column.py`). Отсюда
и предмет проверок: накладка обязана совпадать с таблицей, которую закрывает, —
по строкам, по высоте шапки, по выделению и по ширине колонки, — а иначе она не
закрепление, а второе изображение тех же данных, живущее своей жизнью.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QItemSelectionModel
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


AIRLINES = 8
MONTH_GROUP = (3, 3 + AIRLINES, "Январь 2025")


def pivot_data(rows: int = 14) -> dict:
    """Свод по всем а/к: «Показатель», три служебные графы, месяц и «Итого»."""
    keys = (
        ["indicator", "measure", "code"]
        + [f"m_2025_January_a_{j}" for j in range(AIRLINES)]
        + ["grand_total"]
    )
    headers = (
        ["Показатель", "Ед. изм.", "Код ОКЕИ"]
        + [f"АК {j}" for j in range(AIRLINES)]
        + ["Итого"]
    )
    return {
        "rows": [
            {
                "indicator": f"Показатель {i}", "measure": "тыс. км", "code": str(100 + i),
                **{f"m_2025_January_a_{j}": (i + 1) * (j + 1) for j in range(AIRLINES)},
                "grand_total": i * 10,
            }
            for i in range(rows)
        ],
        "headers": headers,
        "keys": keys,
        "groups": [MONTH_GROUP],
        "stats": {"indicators": rows, "airlines": AIRLINES},
    }


DETAIL_DATA = {"headers": ["ID", "Авиакомпания"], "attrs": ["id", "entity_name"], "records": []}


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrozenColumnCase(unittest.TestCase):
    """Виджет таблицы со сводом на экране; данные подставлены вместо базы."""

    def setUp(self):
        from controllers.report_filters import ReportFilters
        from forms.widgets.data_table_widget import DataTableWidget
        from utils.constants import MODE_AIRLINE

        self.widget = DataTableWidget()
        self.addCleanup(self.widget.deleteLater)
        self.widget.resize(900, 460)
        self.widget.show()

        self.table = self.widget.get_table_view()
        self.frozen = self.widget.frozen_column
        self.mode = MODE_AIRLINE
        self.filters = ReportFilters()
        self.load_pivot()

    def load_pivot(self, rows: int = 14):
        with patch.object(self.widget.data_controller, "load_pivot_data",
                          return_value=pivot_data(rows)):
            self.widget.load_data(self.mode, self.filters)
        QApplication.processEvents()

    def load_detail(self):
        self.widget.radio_detail.setChecked(True)
        with patch.object(self.widget.data_controller, "load_detail_data",
                          return_value=DETAIL_DATA):
            self.widget.load_data(self.mode, self.filters)
        QApplication.processEvents()

    def scroll_right(self, offset: int = 600):
        self.table.horizontalScrollBar().setValue(offset)
        QApplication.processEvents()


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrozenColumnShowsTheIndicatorTest(FrozenColumnCase):
    """Что именно закреплено и остаётся ли оно на месте."""

    def test_only_the_first_column_is_shown(self):
        overlay = self.frozen.view

        self.assertFalse(overlay.isColumnHidden(0))
        for col in range(1, self.widget.pivot_model.columnCount()):
            self.assertTrue(overlay.isColumnHidden(col), f"колонка {col} видна в накладке")

    def test_the_column_is_the_indicator_one(self):
        from PyQt6.QtCore import Qt

        model = self.frozen.view.model()
        self.assertIs(model, self.widget.pivot_model)
        self.assertEqual(
            "Показатель",
            model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole),
        )

    def test_it_stays_put_while_the_table_scrolls_away(self):
        before = self.frozen.view.geometry()

        self.scroll_right()

        # Настоящая первая колонка уехала за левый край — на её месте накладка.
        self.assertLess(self.table.columnViewportPosition(0), 0)
        self.assertEqual(before, self.frozen.view.geometry())
        self.assertTrue(self.frozen.view.isVisible())

    def test_it_is_as_wide_as_the_column_it_repeats(self):
        self.assertEqual(self.table.columnWidth(0), self.frozen.view.width())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrozenColumnLinesUpTest(FrozenColumnCase):
    """Накладка обязана совпадать с таблицей построчно — иначе она врёт."""

    def test_header_heights_match(self):
        """Полоса групп есть и над закреплённой колонкой, хоть она и пустая."""
        self.assertEqual(
            self.widget.grouped_header.height(),
            self.frozen.view.horizontalHeader().height(),
        )

    def test_rows_are_at_the_same_height(self):
        for row in (0, 3, 7):
            with self.subTest(row=row):
                self.assertEqual(
                    self.table.rowViewportPosition(row),
                    self.frozen.view.rowViewportPosition(row),
                )

    def test_scrolling_the_table_scrolls_the_overlay(self):
        self.table.verticalScrollBar().setValue(120)
        QApplication.processEvents()

        self.assertEqual(120, self.frozen.view.verticalScrollBar().value())
        self.assertEqual(
            self.table.rowViewportPosition(5),
            self.frozen.view.rowViewportPosition(5),
        )

    def test_scrolling_the_overlay_scrolls_the_table(self):
        """Колесо мыши над закреплённой колонкой прокручивает весь свод."""
        self.frozen.view.verticalScrollBar().setValue(90)
        QApplication.processEvents()

        self.assertEqual(90, self.table.verticalScrollBar().value())

    def test_selection_is_shared(self):
        self.assertIs(self.table.selectionModel(), self.frozen.view.selectionModel())

        index = self.widget.pivot_model.index(4, 0)
        self.table.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )

        rows = [i.row() for i in self.frozen.view.selectionModel().selectedRows()]
        self.assertEqual([4], rows)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrozenColumnWidthTest(FrozenColumnCase):
    """Ширину колонки по-прежнему можно менять — с любой из двух сторон (BUG-10)."""

    def test_resizing_the_table_column_resizes_the_overlay(self):
        self.table.setColumnWidth(0, 260)
        QApplication.processEvents()

        self.assertEqual(260, self.frozen.view.columnWidth(0))
        self.assertEqual(260, self.frozen.view.width())

    def test_resizing_the_overlay_resizes_the_table_column(self):
        """Границу тянут за заголовок накладки: он лежит поверх настоящего."""
        self.frozen.view.horizontalHeader().resizeSection(0, 300)
        QApplication.processEvents()

        self.assertEqual(300, self.table.columnWidth(0))
        self.assertEqual(300, self.frozen.view.width())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GroupLabelKeepsClearOfTheFrozenColumnTest(FrozenColumnCase):
    """Подпись месяца центрируется по видимой части, а не по области просмотра.

    Область просмотра слева закрыта накладкой: не сказав об этом заголовку, мы
    получили бы подпись, наполовину уехавшую под закреплённую колонку, — на
    экране от «Январь 2025» оставалось «варь 2025».
    """

    def test_header_knows_how_much_of_it_is_covered(self):
        self.assertEqual(
            self.table.columnWidth(0), self.widget.grouped_header._left_cover
        )

    def test_group_label_starts_after_the_frozen_column(self):
        self.scroll_right()
        first, last, _ = MONTH_GROUP

        rect = self.widget.grouped_header._visible_group_rect(first, last, 0)

        self.assertIsNotNone(rect)
        self.assertGreaterEqual(rect.x(), self.table.columnWidth(0))

    def test_nothing_is_covered_once_the_column_is_released(self):
        self.load_detail()

        self.assertEqual(0, self.widget.grouped_header._left_cover)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class CurrentCellStaysVisibleTest(FrozenColumnCase):
    """Курсор не должен уходить под закреплённую колонку.

    Стрелкой влево из середины свода курсор доводится до второй колонки, и
    таблица считает её показанной — в области просмотра она и правда есть, но
    накрыта накладкой.
    """

    def test_scroll_is_pushed_back_so_the_cell_shows(self):
        self.scroll_right()
        # Прокрутка ровно такая, что вторая колонка начинается под накладкой.
        self.table.horizontalScrollBar().setValue(
            self.table.columnViewportPosition(1) + self.table.horizontalScrollBar().value()
        )
        QApplication.processEvents()

        self.table.setCurrentIndex(self.widget.pivot_model.index(0, 1))
        QApplication.processEvents()

        self.assertGreaterEqual(
            self.table.columnViewportPosition(1), self.table.columnWidth(0)
        )

    def test_the_first_column_itself_is_left_alone(self):
        """К самой закреплённой колонке правило не относится: она всегда видна."""
        self.scroll_right()
        before = self.table.horizontalScrollBar().value()

        self.frozen.keep_current_visible(0)

        self.assertEqual(before, self.table.horizontalScrollBar().value())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrozenOnlyInPivotTest(FrozenColumnCase):
    """В подробной таблице первая колонка — «ID», держать её на виду незачем."""

    def test_detail_view_has_no_frozen_column(self):
        self.load_detail()

        self.assertFalse(self.frozen.is_enabled())
        self.assertFalse(self.frozen.view.isVisible())

    def test_it_comes_back_with_the_pivot(self):
        self.load_detail()

        self.widget.radio_pivot.setChecked(True)
        self.load_pivot()

        self.assertTrue(self.frozen.is_enabled())
        self.assertTrue(self.frozen.view.isVisible())
        self.assertIs(self.table.selectionModel(), self.frozen.view.selectionModel())


if __name__ == "__main__":
    unittest.main()
