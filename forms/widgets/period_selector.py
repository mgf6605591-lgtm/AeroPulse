# forms/widgets/period_selector.py
"""Четыре комбобокса периода — общие для обеих вкладок (ARCH-8, ARCH-11).

Заполнение списков, умолчание, применение по кнопке и чтение значений были
списаны в фильтры авиакомпаний и в фильтры аэропортов дословно. Любая правка
периода требовала одинаковых движений в двух файлах — так и разъезжаются
одинаковые куски.

**Годы больше не прибиты к 2020–2030 (ARCH-11).** С 2030 года выбрать текущий
период стало бы невозможно: диапазон был записан в коде числами, при том что
`get_period_range()` уже вычисляет настоящий по данным. Список складывается из
годов, за которые есть отчётность, и текущего года — чтобы на пустой базе
период всё-таки можно было задать.

Список перестраивается и после импорта: отчёт за новый год иначе появился бы в
фильтре только со следующего запуска программы. Выбор при этом сохраняется —
сбрасывать его после импорта нельзя (BUG-25).
"""
from datetime import date
from typing import List, Optional, Sequence, Tuple

from PyQt6.QtWidgets import QComboBox

from utils.constants import APPLY_CAPTION, APPLY_CAPTION_PENDING, MONTHS_RU


def year_choices(data_range: Optional[Tuple[int, int]], today_year: int) -> List[int]:
    """Годы для выбора: всё, за что есть отчётность, плюс текущий год.

    Текущий добавляется всегда: на пустой базе `get_period_range()` отдаёт
    запасной диапазон, и без этого нельзя было бы выбрать период, в котором
    пользователь работает прямо сейчас.
    """
    bounds = [today_year]
    if data_range:
        bounds.extend(year for year in data_range if year)
    # Диапазон сплошной: пропуск года между данными и сегодняшним днём выглядел
    # бы в списке опечаткой, а не осознанным «за этот год отчётности нет».
    return list(range(min(bounds), max(bounds) + 1))


class PeriodSelectorMixin:
    """Поведение периода для виджета фильтров.

    Виджет обязан завести `self.from_month`, `self.from_year`, `self.to_month`,
    `self.to_year`, `self.apply_btn` и `self.filter_controller` — и позвать
    `_init_period_combos()` после того, как комбобоксы созданы.
    """

    def _period_combos(self) -> Sequence[QComboBox]:
        return (self.from_month, self.from_year, self.to_month, self.to_year)

    def _init_period_combos(self) -> None:
        for combo in (self.from_month, self.to_month):
            for key, caption in MONTHS_RU.items():
                combo.addItem(caption, key)
        self._fill_year_combos()
        # Период применяется по кнопке: каждое движение любого из четырёх
        # комбобоксов перестраивало весь отчёт, включая промежуточные состояния
        # вроде «с декабря 2025 по январь 2024» (PERF-4).
        for combo in self._period_combos():
            combo.currentIndexChanged.connect(self._on_period_changed)

    def _fill_year_combos(self) -> None:
        """Заполняет списки годов, сохраняя уже выбранное."""
        min_year, max_year, _, _ = self.filter_controller.get_period_range()
        years = year_choices((min_year, max_year), date.today().year)

        for combo in (self.from_year, self.to_year):
            chosen = combo.currentData()
            combo.blockSignals(True)
            try:
                combo.clear()
                for year in years:
                    combo.addItem(str(year), year)
                if chosen is not None:
                    self._set_combo_value(combo, chosen)
            finally:
                combo.blockSignals(False)

    def _set_combo_value(self, combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _set_default_period(self) -> None:
        """Умолчание — последний год, за который есть данные.

        Прежде брался весь диапазон, от минимального года до максимального. Пока
        одноимённые месяцы разных лет схлопывались в одну колонку (DATA-1), это
        и был спусковой крючок ошибки — она срабатывала сразу при открытии.
        Теперь колонки раздельные, и тот же диапазон дал бы 24+ колонки на старте.
        """
        _, max_year, _, _ = self.filter_controller.get_period_range()
        # Значения ставит программа, а не пользователь: отметка «не применено»
        # тут была бы неправдой.
        for combo in self._period_combos():
            combo.blockSignals(True)
        try:
            self._set_combo_value(self.from_year, max_year)
            self._set_combo_value(self.to_year, max_year)
            self._set_combo_value(self.from_month, "January")
            self._set_combo_value(self.to_month, "December")
        finally:
            for combo in self._period_combos():
                combo.blockSignals(False)
        self._clear_pending()

    def _on_period_changed(self) -> None:
        """Период изменён, но не применён: кнопка показывает, что отчёт устарел."""
        self._period_pending = True
        self.apply_btn.setText(APPLY_CAPTION_PENDING)

    def _clear_pending(self) -> None:
        self._period_pending = False
        self.apply_btn.setText(APPLY_CAPTION)

    # --- чтение выбранного -------------------------------------------------

    def get_from_month(self):
        return self.from_month.currentData()

    def get_from_year(self):
        return self.from_year.currentData()

    def get_to_month(self):
        return self.to_month.currentData()

    def get_to_year(self):
        return self.to_year.currentData()
