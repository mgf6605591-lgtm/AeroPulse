"""Когда отчёт перестраивается (PERF-4, BUG-24).

Период задаётся четырьмя комбобоксами, и каждое их движение перестраивало весь
отчёт: настройка диапазона «с марта 2024 по июнь 2025» стоила четырёх полных
пересчётов, причём промежуточные состояния бессмысленны — «с декабря 2025 по
январь 2024» (PERF-4). Кнопка «Применить» при этом уже была.

Переключение режима отображения давало два пересчёта на один клик: `toggled`
испускается и у включаемой кнопки, и у выключаемой, а подписаны были обе
(BUG-24).

Считаются именно сигналы и вызовы перезагрузки — то, сколько раз приложение
возьмётся строить отчёт.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.constants import APPLY_CAPTION, APPLY_CAPTION_PENDING

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


class PeriodAppliesByButton:
    """Общее для обеих вкладок: период ждёт кнопку.

    Не наследует TestCase намеренно: иначе набор проверок выполнялся бы ещё и
    сам по себе, без виджета.
    """

    def make_widget(self):
        raise NotImplementedError

    def setUp(self):
        self.widget = self.make_widget()
        self.addCleanup(self.widget.deleteLater)
        self.rebuilds = []
        self.widget.filters_changed.connect(lambda: self.rebuilds.append(1))

    def change_period(self):
        """Диапазон «с марта 2024 по июнь 2025» — четыре движения."""
        self.widget._set_combo_value(self.widget.from_month, "March")
        self.widget._set_combo_value(self.widget.from_year, 2024)
        self.widget._set_combo_value(self.widget.to_month, "June")
        self.widget._set_combo_value(self.widget.to_year, 2025)

    def test_changing_the_period_does_not_rebuild(self):
        self.change_period()

        self.assertEqual([], self.rebuilds)

    def test_apply_rebuilds_once(self):
        self.change_period()

        self.widget.apply_btn.click()

        self.assertEqual(1, len(self.rebuilds))

    def test_button_says_the_report_is_stale(self):
        self.change_period()

        self.assertEqual(APPLY_CAPTION_PENDING, self.widget.apply_btn.text())

    def test_button_returns_to_normal_after_apply(self):
        self.change_period()

        self.widget.apply_btn.click()

        self.assertEqual(APPLY_CAPTION, self.widget.apply_btn.text())

    def test_default_period_is_not_marked_as_pending(self):
        """Значения ставит программа: отметка «не применено» была бы неправдой."""
        self.widget._set_default_period()

        self.assertEqual(APPLY_CAPTION, self.widget.apply_btn.text())
        self.assertEqual([], self.rebuilds)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AirlineFilterApplyTest(PeriodAppliesByButton, unittest.TestCase):
    def make_widget(self):
        from forms.widgets.filter_widget import FilterWidget

        return FilterWidget()

    def test_choosing_indicators_still_rebuilds_at_once(self):
        """Один выбор — одно осмысленное состояние, ждать кнопку незачем."""
        self.widget.indicator_btn.selectionChanged.emit()

        self.assertEqual(1, len(self.rebuilds))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AirportFilterApplyTest(PeriodAppliesByButton, unittest.TestCase):
    def make_widget(self):
        from forms.widgets.airport_filter_widget import AirportFilterWidget

        return AirportFilterWidget()

    def test_choosing_the_airports_still_rebuilds_at_once(self):
        self.widget.airport_btn.selectionChanged.emit()

        self.assertEqual(1, len(self.rebuilds))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ViewToggleTest(unittest.TestCase):
    """BUG-24: один клик — одна перезагрузка."""

    def setUp(self):
        from forms.widgets.data_table_widget import DataTableWidget

        self.widget = DataTableWidget()
        self.addCleanup(self.widget.deleteLater)
        # О перестроении виджет сообщает сигналом, а не вызовом метода родителя
        # (ARCH-10): считаем испускания.
        self.reloads = []
        self.widget.reload_requested.connect(lambda: self.reloads.append(1))

    def test_switching_to_detail_reloads_once(self):
        """Прежде здесь было две перезагрузки: сигнал шёл от обеих кнопок."""
        self.widget.radio_detail.setChecked(True)

        self.assertEqual(1, len(self.reloads))

    def test_switching_back_reloads_once(self):
        self.widget.radio_detail.setChecked(True)
        self.reloads.clear()

        self.widget.radio_pivot.setChecked(True)

        self.assertEqual(1, len(self.reloads))

    def test_view_and_delete_button_follow_the_mode(self):
        from utils.constants import VIEW_DETAIL, VIEW_PIVOT

        self.widget.radio_detail.setChecked(True)
        self.assertEqual(VIEW_DETAIL, self.widget.current_view)
        self.assertTrue(self.widget.delete_btn.isEnabled())

        self.widget.radio_pivot.setChecked(True)
        self.assertEqual(VIEW_PIVOT, self.widget.current_view)
        self.assertFalse(self.widget.delete_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
