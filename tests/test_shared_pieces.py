"""Общие куски вместо копий и явные контракты (ARCH-8…ARCH-11).

Одно и то же было выписано в нескольких местах: две одинаковые отрисовки секции
заголовка, два одинаковых построителя пустой строки свода, четыре комбобокса
периода в обеих вкладках и список месяцев — в каждом парсере свой. Виджеты при
этом звали методы родителя через `hasattr`, а годы в фильтрах были прибиты
числами: с 2030 года выбрать текущий период стало бы невозможно.

Проверяется не «код красивее», а следствия: список годов считается по данным,
сигнал доходит вместо вызова по имени, месяц во всех парсерах один.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from db.models.enums import Months
from utils.months import (
    MONTH_NAMES,
    month_from_period,
    month_name,
    period_from_meta_filename,
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


if HAS_QT:
    from forms.widgets.period_selector import year_choices


class MonthTableIsOneTest(unittest.TestCase):
    """ARCH-8: список месяцев был выписан заново в каждом парсере."""

    def test_names_come_from_the_enum_that_the_database_uses(self):
        self.assertEqual(tuple(m.name for m in Months), MONTH_NAMES)

    def test_number_gives_the_name(self):
        self.assertEqual("January", month_name(1))
        self.assertEqual("December", month_name(12))

    def test_number_outside_the_range_gives_nothing(self):
        for number in (0, 13, -1):
            self.assertIsNone(month_name(number), number)

    def test_parsers_keep_no_copies(self):
        """Своя таблица в парсере снова разошлась бы с базой молча."""
        from pathlib import Path

        parsers = Path(__file__).resolve().parent.parent / "parsers"
        offenders = [
            path.name for path in parsers.glob("*.py")
            if "_MONTH_ENUM" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)


class MonthFromXmlTest(unittest.TestCase):
    """Разбор месяца был списан в оба разборщика XML дословно."""

    def test_period_attribute_ends_with_the_month(self):
        self.assertEqual("February", month_from_period("202502"))
        self.assertEqual("December", month_from_period("12"))

    def test_single_digit_period_is_a_month(self):
        """В настоящих выгрузках ведущего нуля нет: январь записан как «1».

        Разбор требовал двух цифр и на месяцах с первого по девятый возвращал
        None — период не определялся у трёх четвертей файлов годового комплекта,
        и импорт отказывал, хотя месяц в файле проставлен.
        """
        for digit, month in enumerate(("January", "February", "March", "April", "May",
                                       "June", "July", "August", "September"), start=1):
            with self.subTest(period=digit):
                self.assertEqual(month, month_from_period(str(digit)))

    def test_period_without_a_month_gives_nothing(self):
        for value in ("", None, "abc", "0", "2025", "202513", "202500"):
            self.assertIsNone(month_from_period(value), value)

    def test_period_is_taken_from_the_file_name_as_a_fallback(self):
        self.assertEqual(("March", 2025), period_from_meta_filename("f15_2025_03_meta.xml"))
        self.assertEqual(
            ("March", 2025), period_from_meta_filename(r"C:\reports\f15_2025_03_meta.xml")
        )

    def test_the_last_two_numbers_of_a_real_export_are_the_period(self):
        """Имя выгрузки кончается годом и месяцем, и ведущего нуля у месяца нет.

        `0615106_12_12_2269_2025_1.xml` — 12-ГА АО «Авиакомпания АЛРОСА» за январь
        2025. Разбор требовал двух цифр месяца и подчёркивания за ними, поэтому у
        настоящих файлов не срабатывал ни разу, а год из имени не читался вовсе.
        """
        self.assertEqual(
            ("January", 2025), period_from_meta_filename("0615106_12_12_2269_2025_1.xml")
        )
        self.assertEqual(
            ("December", 2025), period_from_meta_filename("0615107_15_12_293_2025_12.xml")
        )

    def test_numbers_before_the_period_are_not_mistaken_for_it(self):
        """Перед годом стоят номер формы, код периодичности и код предприятия."""
        self.assertEqual(
            ("May", 2025), period_from_meta_filename("0615106_12_12_2542_2025_5.xml")
        )

    def test_file_name_without_a_period_gives_nothing(self):
        self.assertEqual((None, None), period_from_meta_filename("f15_meta.xml"))

    def test_a_number_that_is_not_a_month_is_not_a_period(self):
        """Год без месяца не берётся: разобрана не та пара, и это видно."""
        self.assertEqual((None, None), period_from_meta_filename("f15_2025_13.xml"))
        self.assertEqual((None, None), period_from_meta_filename("f15_2025_0.xml"))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class YearChoicesFollowTheDataTest(unittest.TestCase):
    """ARCH-11: годы были записаны числами — `range(2020, 2030)`."""

    def test_data_years_are_offered(self):
        self.assertEqual([2023, 2024, 2025], year_choices((2023, 2025), today_year=2024))

    def test_current_year_is_always_offered(self):
        """На пустой базе иначе нельзя было бы выбрать период, в котором работаешь."""
        self.assertIn(2031, year_choices(None, today_year=2031))

    def test_current_year_extends_the_data_range(self):
        self.assertEqual([2024, 2025, 2026, 2027], year_choices((2024, 2025), today_year=2027))

    def test_range_beyond_2030_is_no_longer_a_problem(self):
        """С прежним списком 2031-й год выбрать было нельзя вовсе."""
        self.assertIn(2031, year_choices((2030, 2031), today_year=2031))

    def test_years_are_sorted_and_unique(self):
        years = year_choices((2025, 2023), today_year=2024)

        self.assertEqual(sorted(set(years)), years)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class BothTabsShareThePeriodBlockTest(unittest.TestCase):
    """ARCH-8: заполнение, умолчание и чтение периода были списаны в оба виджета."""

    def widgets(self):
        from forms.widgets.airport_filter_widget import AirportFilterWidget
        from forms.widgets.filter_widget import FilterWidget

        for widget in (FilterWidget(), AirportFilterWidget()):
            self.addCleanup(widget.deleteLater)
            yield widget

    def test_both_take_the_block_from_one_place(self):
        from forms.widgets.period_selector import PeriodSelectorMixin

        for widget in self.widgets():
            self.assertIsInstance(widget, PeriodSelectorMixin)

    def test_both_offer_the_current_year(self):
        this_year = date.today().year

        for widget in self.widgets():
            years = [widget.from_year.itemData(i) for i in range(widget.from_year.count())]
            self.assertIn(this_year, years, type(widget).__name__)

    def test_both_read_the_period_the_same_way(self):
        for widget in self.widgets():
            self.assertIsNotNone(widget.get_from_month(), type(widget).__name__)
            self.assertIsNotNone(widget.get_to_year(), type(widget).__name__)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WidgetsTalkBySignalsTest(unittest.TestCase):
    """ARCH-10: виджет звал метод родителя, а связь ставилась постфактум.

    `hasattr(self, 'parent')` у любого `QObject` истинно — это метод, — так что
    проверка ничего не проверяла.
    """

    def test_table_reports_a_view_change_by_signal(self):
        from forms.widgets.data_table_widget import DataTableWidget

        widget = DataTableWidget()
        self.addCleanup(widget.deleteLater)
        seen = []
        widget.reload_requested.connect(lambda: seen.append(1))

        widget.radio_detail.setChecked(True)

        self.assertEqual([1], seen)

    def test_table_no_longer_holds_its_parent(self):
        from forms.widgets.data_table_widget import DataTableWidget

        widget = DataTableWidget()
        self.addCleanup(widget.deleteLater)

        self.assertFalse(hasattr(widget, "set_parent_window"))
        self.assertFalse(hasattr(widget, "parent_window"))

    def test_import_dialog_reports_a_type_change_by_signal(self):
        from forms.widgets.import_dialog import ImportDialog

        dialog = ImportDialog()
        self.addCleanup(dialog.deleteLater)
        seen = []
        dialog.type_changed.connect(seen.append)

        dialog.type_combo.setCurrentIndex(1)

        self.assertEqual(["airport"], seen)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class NoTwinsLeftTest(unittest.TestCase):
    """Две пары методов-близнецов, отличавшихся только именем."""

    def test_header_paints_a_section_by_one_method(self):
        from forms.widgets.multilevel_header import MultiLevelHeaderView

        self.assertTrue(hasattr(MultiLevelHeaderView, "_paint_section"))
        self.assertFalse(hasattr(MultiLevelHeaderView, "_paint_standard_section"))
        self.assertFalse(hasattr(MultiLevelHeaderView, "_paint_section_no_hover"))

    def test_empty_pivot_rows_are_built_by_one_function(self):
        from controllers.data_controller import (
            _pivot_section_header_row,
            _pivot_subheading_row,
            _pivot_text_row,
        )

        keys = ["indicator", "measure", "m_2025_January_total"]
        self.assertEqual(_pivot_text_row(keys, "в том числе:"),
                         _pivot_subheading_row(keys, "в том числе:"))
        self.assertEqual(_pivot_text_row(keys, "— РАЗДЕЛ —"),
                         _pivot_section_header_row(keys, "РАЗДЕЛ"))

    def test_section_header_is_decorated_and_subheading_is_not(self):
        """Отличие у них было ровно одно — оформление подписи."""
        from controllers.data_controller import (
            _pivot_section_header_row,
            _pivot_subheading_row,
        )

        keys = ["indicator", "measure"]
        self.assertEqual("— РАЗДЕЛ —", _pivot_section_header_row(keys, "РАЗДЕЛ")["indicator"])
        self.assertEqual("в том числе:", _pivot_subheading_row(keys, "в том числе:")["indicator"])


if __name__ == "__main__":
    unittest.main()
