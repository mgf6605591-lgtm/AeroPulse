"""Порядок границ периода и тип предприятия в диалоге импорта (BUG-16, FUNC-12).

Границы периода брались из комбобоксов как есть. Выбрав «с декабря 2025 по
январь 2024», пользователь получал пустой отчёт: условие отбора
«начало ≤ ключ ≤ конец» не выполняется ни для одной записи — и ни одного
объяснения, почему таблица пуста (BUG-16).

Диалог импорта всегда открывался на «Авиакомпании» независимо от вкладки: с
вкладки аэропортов пользователь получал список авиакомпаний и, не заметив
этого, упирался в отказ по несовпадению формы (FUNC-12).

Окна создаются на платформе offscreen — на экране не появляется ничего.
Модальное предупреждение подменяется: иначе прогон встал бы на нём.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from controllers.filter_controller import period_from_widget, period_is_inverted
from tests.support import FilterWidgetCase
from utils.constants import MODE_AIRLINE, MODE_AIRPORT

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


class FakePeriodWidget:
    """Комбобоксы периода в том виде, в каком их читает контроллер."""

    def __init__(self, from_month="January", from_year=2025,
                 to_month="March", to_year=2025):
        self._values = (from_month, from_year, to_month, to_year)

    def get_from_month(self):
        return self._values[0]

    def get_from_year(self):
        return self._values[1]

    def get_to_month(self):
        return self._values[2]

    def get_to_year(self):
        return self._values[3]


class PeriodBoundsTest(unittest.TestCase):
    """Чтение периода — одно на обе вкладки, где оно было списано дословно."""

    def test_bounds_are_year_and_month_number(self):
        bounds = period_from_widget(FakePeriodWidget("January", 2025, "March", 2025))

        self.assertEqual(((2025, 1), (2025, 3)), bounds)

    def test_incomplete_period_gives_nothing(self):
        self.assertIsNone(period_from_widget(FakePeriodWidget(from_month=None)))
        self.assertIsNone(period_from_widget(FakePeriodWidget(to_year=None)))


class PeriodOrderTest(unittest.TestCase):
    """Разворот границ виден по самим границам, без обращения к базе."""

    def inverted(self, **kwargs):
        return period_is_inverted(period_from_widget(FakePeriodWidget(**kwargs)))

    def test_straight_period_is_fine(self):
        self.assertFalse(self.inverted(from_month="January", to_month="March"))

    def test_single_month_is_fine(self):
        self.assertFalse(self.inverted(from_month="March", to_month="March"))

    def test_reversed_months_within_a_year(self):
        self.assertTrue(self.inverted(from_month="March", to_month="January"))

    def test_reversed_years(self):
        """Тот самый пример из разбора: с декабря 2025 по январь 2024."""
        self.assertTrue(self.inverted(from_month="December", from_year=2025,
                                      to_month="January", to_year=2024))

    def test_later_month_of_an_earlier_year_is_still_earlier(self):
        """Месяц сам по себе порядка не задаёт: декабрь 2024 раньше января 2025."""
        self.assertFalse(self.inverted(from_month="December", from_year=2024,
                                       to_month="January", to_year=2025))

    def test_missing_period_is_not_an_error(self):
        self.assertFalse(period_is_inverted(None))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ApplyRefusesAnInvertedPeriodTest(FilterWidgetCase):
    """Поведение по кнопке «Применить»: сказать и не строить.

    Границы намеренно не переставляются местами: перестановка выглядит услугой,
    но даёт отчёт за двадцать четыре месяца, которого никто не просил.

    Годы 2024 и 2025 приходят из фикстуры: на рабочей базе разработчика набор
    годов какой угодно, и «с декабря 2025 по январь 2024» было не выбрать.
    """

    def make_widget(self, cls_name):
        if cls_name == "airline":
            from forms.widgets.filter_widget import FilterWidget
            widget = FilterWidget()
        else:
            from forms.widgets.airport_filter_widget import AirportFilterWidget
            widget = AirportFilterWidget()
        self.addCleanup(widget.deleteLater)
        return widget

    def set_period(self, widget, from_month, from_year, to_month, to_year):
        for combo, value in (
            (widget.from_month, from_month), (widget.from_year, from_year),
            (widget.to_month, to_month), (widget.to_year, to_year),
        ):
            for i in range(combo.count()):
                if combo.itemData(i) == value:
                    combo.setCurrentIndex(i)
                    break
            else:
                self.fail(f"в списке нет значения {value!r}")

    def apply(self, widget):
        rebuilt = []
        widget.filters_changed.connect(lambda: rebuilt.append(1))
        with patch("forms.widgets.period_guard.QMessageBox.warning") as warning:
            widget._on_apply()
        return rebuilt, warning

    def test_inverted_period_does_not_rebuild_the_report(self):
        widget = self.make_widget("airline")
        self.set_period(widget, "December", 2025, "January", 2024)

        rebuilt, warning = self.apply(widget)

        self.assertEqual([], rebuilt)
        self.assertTrue(warning.called)

    def test_the_message_names_both_bounds(self):
        widget = self.make_widget("airline")
        self.set_period(widget, "December", 2025, "January", 2024)

        _, warning = self.apply(widget)

        text = warning.call_args.args[2]
        self.assertIn("Декабрь 2025", text)
        self.assertIn("Январь 2024", text)

    def test_bounds_are_left_as_the_user_set_them(self):
        """Комбобоксы не трогаются: поправить их — дело человека, а не программы."""
        widget = self.make_widget("airline")
        self.set_period(widget, "December", 2025, "January", 2024)

        self.apply(widget)

        self.assertEqual("December", widget.from_month.currentData())
        self.assertEqual(2024, widget.to_year.currentData())

    def test_report_stays_marked_as_outdated(self):
        """Отчёт и правда устарел — отметка «не применено» должна остаться."""
        widget = self.make_widget("airline")
        self.set_period(widget, "December", 2025, "January", 2024)

        self.apply(widget)

        self.assertTrue(widget._period_pending)

    def test_straight_period_rebuilds_as_before(self):
        widget = self.make_widget("airline")
        self.set_period(widget, "January", 2025, "March", 2025)

        rebuilt, warning = self.apply(widget)

        self.assertEqual([1], rebuilt)
        self.assertFalse(warning.called)
        self.assertFalse(widget._period_pending)

    def test_airport_tab_is_guarded_too(self):
        """Обе вкладки применяют период одной кнопкой — и правило у них одно."""
        widget = self.make_widget("airport")
        self.set_period(widget, "December", 2025, "January", 2024)

        rebuilt, warning = self.apply(widget)

        self.assertEqual([], rebuilt)
        self.assertTrue(warning.called)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ImportDialogOpensOnTheActiveTabTest(unittest.TestCase):
    """FUNC-12: тип предприятия — по вкладке, с которой позвали импорт."""

    def make_dialog(self):
        from forms.widgets.import_dialog import ImportDialog

        dialog = ImportDialog()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_default_is_still_airline(self):
        self.assertEqual("airline", self.make_dialog().get_type())

    def test_type_can_be_preselected(self):
        dialog = self.make_dialog()

        dialog.select_type("airport")

        self.assertEqual("airport", dialog.get_type())

    def test_unknown_type_changes_nothing(self):
        dialog = self.make_dialog()

        dialog.select_type("вертолётная площадка")

        self.assertEqual("airline", dialog.get_type())

    def test_window_opens_the_dialog_for_the_active_tab(self):
        """Связка: тип берётся из current_mode главного окна.

        Окно поднимается без своего `__init__` — заполнять его вкладками и
        таблицами значило бы поднимать базу ради выбора одной строки в списке.
        """
        from PyQt6.QtWidgets import QMainWindow

        from forms.mainWin import MainWindow

        window = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)

        chosen = []
        window.refresh_entities = lambda entity_type, combo: chosen.append(entity_type)

        for mode, expected in ((MODE_AIRLINE, "airline"), (MODE_AIRPORT, "airport")):
            chosen.clear()
            window.current_mode = mode
            with patch("forms.mainWin.QFileDialog.getOpenFileNames",
                       return_value=(["отчёт.xlsx"], "")), \
                 patch("forms.widgets.import_dialog.ImportDialog.exec", return_value=0):
                window.import_file()

            self.assertEqual([expected], chosen)


if __name__ == "__main__":
    unittest.main()
