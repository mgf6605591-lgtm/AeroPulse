"""Обновление фильтров после импорта и правки справочников (BUG-7, ARCH-7, BUG-25).

Два дефекта одной природы — инвалидация была точечной вместо общей:

* кешей справочников было четыре, по одному на экземпляр `FilterController`, и
  после импорта сбрасывался тот, что в фильтрах не участвует: вкладка
  «Авиакомпании» показывала прежние списки до перезапуска программы (BUG-7);
* вкладка аэропортов, наоборот, перечитывала всё подряд и вместе со списками
  сбрасывала период и выбор показателей, хотя обновить требовалось справочники
  (BUG-25).

Проверяется поведение виджетов на платформе offscreen: списки читаются из
подменённого контроллера, а состояние фильтров — из самих виджетов Qt.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from controllers.filter_controller import FilterController
from controllers.reference_cache import ReferenceDataCache

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


# Без пункта «Все»: контроллер отдаёт только сами записи справочника (PERF-9).
AIRLINES_BEFORE = [(1, "Первая АК")]
AIRLINES_AFTER = [(1, "Первая АК"), (2, "Вторая АК")]
AIRPORTS_BEFORE = [(10, "Первый аэропорт")]
AIRPORTS_AFTER = [(10, "Первый аэропорт"), (20, "Второй аэропорт")]
INDICATORS_BEFORE = [(100, "Налет часов")]
INDICATORS_AFTER = [(100, "Налет часов"), (200, "Самолето-километры")]


class FakeReference:
    """Справочники в том виде, в каком их отдаёт FilterController.

    Между «до» и «после» переключается вручную: так выглядит появление новой
    записи после импорта.
    """

    def __init__(self):
        self.grown = False
        self.max_year = 2025

    def load_entities(self, mode):
        from utils.constants import MODE_AIRLINE

        if mode == MODE_AIRLINE:
            return AIRLINES_AFTER if self.grown else AIRLINES_BEFORE
        return AIRPORTS_AFTER if self.grown else AIRPORTS_BEFORE

    def load_indicators(self):
        return INDICATORS_AFTER if self.grown else INDICATORS_BEFORE

    def get_period_range(self):
        return 2020, self.max_year, 1, 12

    def clear_cache(self):
        pass


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WidgetCase(unittest.TestCase):
    def setUp(self):
        self.reference = FakeReference()
        patcher = patch(
            "controllers.filter_controller.FilterController.load_entities",
            side_effect=self.reference.load_entities,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        indicators = patch(
            "controllers.filter_controller.FilterController.load_indicators",
            side_effect=self.reference.load_indicators,
        )
        indicators.start()
        self.addCleanup(indicators.stop)

        period = patch(
            "controllers.filter_controller.FilterController.get_period_range",
            side_effect=self.reference.get_period_range,
        )
        period.start()
        self.addCleanup(period.stop)


class AirlineFilterRefreshTest(WidgetCase):
    """Вкладка «Авиакомпании»: новая запись появляется в списках (BUG-7)."""

    def make_widget(self):
        from forms.widgets.filter_widget import FilterWidget

        widget = FilterWidget()
        self.addCleanup(widget.deleteLater)
        return widget

    def test_new_airline_appears_after_reload(self):
        widget = self.make_widget()
        self.assertEqual(1, len(widget.entity_btn._items))

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual(2, len(widget.entity_btn._items))

    def test_new_indicator_appears_after_reload(self):
        widget = self.make_widget()

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual(2, len(widget.indicator_btn._items))

    def test_period_survives_the_reload(self):
        widget = self.make_widget()
        widget._set_combo_value(widget.from_year, 2021)
        widget._set_combo_value(widget.from_month, "March")

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual(2021, widget.get_from_year())
        self.assertEqual("March", widget.get_from_month())

    def test_selection_survives_the_reload(self):
        widget = self.make_widget()
        widget.indicator_btn._selected = {100}

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual([100], widget.get_indicator_filter_ids())


class AirportFilterRefreshTest(WidgetCase):
    """Вкладка «Аэропорты»: обновление списков не сбрасывает настройки (BUG-25)."""

    def make_widget(self):
        from forms.widgets.airport_filter_widget import AirportFilterWidget

        widget = AirportFilterWidget()
        self.addCleanup(widget.deleteLater)
        return widget

    def test_new_airport_appears_after_reload(self):
        widget = self.make_widget()
        self.assertEqual(1, len(widget.airport_btn._items))

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual(2, len(widget.airport_btn._items))

    def test_chosen_airport_survives_the_reload(self):
        widget = self.make_widget()
        widget.airport_btn._selected = {10}
        self.reference.grown = True

        widget.reload_reference_lists()

        # Пока в списке больше одного аэропорта, выбор одного — это отбор, а не «все».
        self.assertEqual([10], widget.get_airport_filter_ids())

    def test_period_survives_the_reload(self):
        """То, что терялось после каждого импорта."""
        widget = self.make_widget()
        widget._set_combo_value(widget.from_year, 2021)
        widget._set_combo_value(widget.from_month, "March")
        widget._set_combo_value(widget.to_year, 2022)

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual(2021, widget.get_from_year())
        self.assertEqual("March", widget.get_from_month())
        self.assertEqual(2022, widget.get_to_year())

    def test_indicator_selection_survives_the_reload(self):
        widget = self.make_widget()
        widget.indicator_btn._selected = {100}

        self.reference.grown = True
        widget.reload_reference_lists()

        self.assertEqual([100], widget.get_indicator_filter_ids())

    def test_reset_still_returns_the_default_period(self):
        """Сброс фильтров — единственное место, где период возвращается к умолчанию."""
        widget = self.make_widget()
        widget._set_combo_value(widget.from_year, 2021)

        widget.reset_filters()

        self.assertEqual(2025, widget.get_from_year())


class SharedCacheTest(unittest.TestCase):
    """Кеш справочников один на приложение (ARCH-7)."""

    def test_instances_share_one_cache(self):
        cache = ReferenceDataCache()
        first = FilterController(cache)
        second = FilterController(cache)

        cache.put_indicators(INDICATORS_BEFORE)

        self.assertEqual(INDICATORS_BEFORE, second.load_indicators())
        self.assertEqual(INDICATORS_BEFORE, first.load_indicators())

    def test_invalidation_by_one_is_seen_by_all(self):
        """Прежде сброс одного экземпляра не касался остальных — это и был BUG-7."""
        cache = ReferenceDataCache()
        first = FilterController(cache)
        second = FilterController(cache)
        cache.put_indicators(INDICATORS_BEFORE)

        first.clear_cache()

        self.assertIsNone(cache.indicators())
        # После сброса второй контроллер идёт в базу, а не отдаёт прежний список.
        # Подмена get_session обрывает обращение, и виден резервный ответ — он и
        # доказывает, что попытка чтения была.
        with patch("controllers.filter_controller.get_session", side_effect=RuntimeError("нет базы")):
            self.assertEqual([], second.load_indicators())

    def test_default_cache_is_the_application_wide_one(self):
        from controllers.reference_cache import reference_cache

        self.assertIs(reference_cache, FilterController()._cache)


if __name__ == "__main__":
    unittest.main()
