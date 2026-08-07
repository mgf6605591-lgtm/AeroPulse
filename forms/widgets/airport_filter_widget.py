# forms/widgets/airport_filter_widget.py
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QComboBox,
    QLabel,
    QPushButton,
    QGroupBox,
)
from PyQt6.QtCore import pyqtSignal

from controllers.filter_controller import FilterController
from forms.widgets.multi_select_filter_button import MultiSelectFilterButton
from utils.constants import APPLY_CAPTION, APPLY_CAPTION_PENDING, MONTHS_RU, MODE_AIRPORT


class AirportFilterWidget(QGroupBox):
    """Фильтры вкладки аэропортов: один аэропорт из выпадающего списка, показатели, период."""

    filters_changed = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Фильтры (форма 15-ГА)", parent)
        self.filter_controller = FilterController()
        self._period_pending = False
        self._init_ui()
        self._load_lists()

    def _init_ui(self):
        main = QVBoxLayout(self)

        row_filters = QHBoxLayout()
        self.airport_combo = QComboBox()
        self.airport_combo.setMinimumWidth(320)
        self.airport_combo.currentIndexChanged.connect(self._on_filters_changed)

        self.indicator_btn = MultiSelectFilterButton("Показатели")
        self.indicator_btn.setMinimumWidth(200)
        self.indicator_btn.selectionChanged.connect(self._on_filters_changed)

        self.apply_btn = QPushButton(APPLY_CAPTION)
        self.apply_btn.clicked.connect(self._on_apply)
        self.reset_btn = QPushButton("Сбросить")
        self.reset_btn.clicked.connect(self.reset_requested.emit)

        row_filters.addWidget(QLabel("Аэропорт:"))
        row_filters.addWidget(self.airport_combo)
        row_filters.addWidget(QLabel("Показатель:"))
        row_filters.addWidget(self.indicator_btn)
        row_filters.addStretch()
        row_filters.addWidget(self.apply_btn)
        row_filters.addWidget(self.reset_btn)

        row_period = QHBoxLayout()
        self.from_month = QComboBox()
        self.from_year = QComboBox()
        self.to_month = QComboBox()
        self.to_year = QComboBox()
        for combo in (self.from_month, self.to_month):
            for key, val in MONTHS_RU.items():
                combo.addItem(val, key)
        for combo in (self.from_year, self.to_year):
            for y in range(2020, 2030):
                combo.addItem(str(y), y)
        # Период применяется по кнопке: каждое движение любого из четырёх
        # комбобоксов перестраивало весь отчёт, включая промежуточные состояния
        # вроде «с декабря 2025 по январь 2024» (PERF-4).
        for combo in self._period_combos():
            combo.currentIndexChanged.connect(self._on_period_changed)

        row_period.addWidget(QLabel("Период с:"))
        row_period.addWidget(self.from_month)
        row_period.addWidget(self.from_year)
        row_period.addWidget(QLabel("по:"))
        row_period.addWidget(self.to_month)
        row_period.addWidget(self.to_year)
        row_period.addStretch()

        main.addLayout(row_filters)
        main.addLayout(row_period)

    def _load_lists(self):
        """Первое заполнение: справочники и период по умолчанию."""
        self._load_airports()
        self._load_indicators()
        self._set_default_period()

    def _load_airports(self, keep_selection: bool = False):
        current = self.get_airport_id() if keep_selection else None
        entities = self.filter_controller.load_entities(MODE_AIRPORT)
        self.airport_combo.blockSignals(True)
        try:
            self.airport_combo.clear()
            self.airport_combo.addItem("— выберите аэропорт —", None)
            for eid, label in entities:
                if eid is not None:
                    self.airport_combo.addItem(label, int(eid))
            if current is not None:
                for i in range(self.airport_combo.count()):
                    if self.airport_combo.itemData(i) == current:
                        self.airport_combo.setCurrentIndex(i)
                        break
        finally:
            self.airport_combo.blockSignals(False)

    def _load_indicators(self, keep_selection: bool = False):
        indicators = self.filter_controller.load_indicators()
        items = [(iid, label) for iid, label in indicators if iid is not None]
        # set_items оставляет из выбора только то, что есть в новом списке.
        self.indicator_btn.set_items(items)
        if not keep_selection:
            self.indicator_btn.clear_selection()

    def _set_default_period(self):
        # Умолчание — последний год с данными, а не весь их диапазон: раздельные
        # колонки по годам (DATA-1) иначе дали бы 24+ колонки при открытии.
        _, max_year, _, _ = self.filter_controller.get_period_range()
        # Значения ставит программа: отметка «не применено» тут была бы неправдой.
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

    def _set_combo_value(self, combo: QComboBox, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _period_combos(self):
        return (self.from_month, self.from_year, self.to_month, self.to_year)

    def _on_filters_changed(self):
        self.filters_changed.emit()

    def _on_period_changed(self):
        """Период изменён, но не применён: кнопка показывает, что отчёт устарел."""
        self._period_pending = True
        self.apply_btn.setText(APPLY_CAPTION_PENDING)

    def _on_apply(self):
        self._clear_pending()
        self.filters_changed.emit()

    def _clear_pending(self):
        self._period_pending = False
        self.apply_btn.setText(APPLY_CAPTION)

    def get_airport_id(self):
        return self.airport_combo.currentData()

    def get_indicator_filter_ids(self):
        return self.indicator_btn.filter_active_ids()

    def get_from_month(self):
        return self.from_month.currentData()

    def get_from_year(self):
        return self.from_year.currentData()

    def get_to_month(self):
        return self.to_month.currentData()

    def get_to_year(self):
        return self.to_year.currentData()

    def reset_filters(self):
        self.airport_combo.setCurrentIndex(0)
        self.indicator_btn.clear_selection()
        # Сброс возвращает то же умолчание, что и первое открытие.
        self._set_default_period()

    def reload_reference_lists(self):
        """Перечитать справочники, сохранив выбор аэропорта, показателей и период.

        Прежний метод вызывал `_load_lists()` целиком: он честно возвращал
        выбранный аэропорт, но молча сбрасывал период на умолчание и снимал
        фильтр показателей, хотя обновить требовалось только справочники (BUG-25).
        Сброс кеша здесь не делается — он общий и сбрасывается один раз тем, кто
        менял данные (BUG-7).
        """
        self._load_airports(keep_selection=True)
        self._load_indicators(keep_selection=True)
