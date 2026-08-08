# forms/widgets/filter_widget.py
from PyQt6.QtWidgets import (
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
from forms.widgets.period_guard import period_is_usable
from utils.constants import (
    APPLY_CAPTION,
    APPLY_CAPTION_PENDING,
    MONTHS_RU,
    MODE_AIRLINE,
    PIVOT_LAYOUT_BY_ROUTES,
    PIVOT_LAYOUT_SUMMARY,
)
from db.models.enums import RouteType


class FilterWidget(QGroupBox):
    """Фильтры: множественный выбор а/к или аэропортов, показателей, маршрутов (как в маркетплейсах)."""

    filters_changed = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Фильтры", parent)
        self.filter_controller = FilterController()
        self.current_mode = MODE_AIRLINE
        self._period_pending = False
        self._init_ui()
        self._load_initial_data()

    def _init_ui(self):
        main = QVBoxLayout(self)

        row_filters = QHBoxLayout()
        self.entity_label = QLabel("Авиакомпания:")
        self.entity_btn = MultiSelectFilterButton("Авиакомпании")
        self.entity_btn.setMinimumWidth(200)
        self.entity_btn.selectionChanged.connect(self._on_filters_changed)

        self.indicator_btn = MultiSelectFilterButton("Показатели")
        self.indicator_btn.setMinimumWidth(200)
        self.indicator_btn.selectionChanged.connect(self._on_filters_changed)

        self.route_btn = MultiSelectFilterButton("Маршрут")
        self.route_btn.setMinimumWidth(180)
        self.route_btn.selectionChanged.connect(self._on_filters_changed)

        self.apply_btn = QPushButton(APPLY_CAPTION)
        self.apply_btn.clicked.connect(self._on_apply)
        self.reset_btn = QPushButton("Сбросить")
        self.reset_btn.clicked.connect(self.reset_requested.emit)

        row_filters.addWidget(self.entity_label)
        row_filters.addWidget(self.entity_btn)
        row_filters.addWidget(QLabel("Показатель:"))
        row_filters.addWidget(self.indicator_btn)
        row_filters.addWidget(QLabel("Маршрут:"))
        row_filters.addWidget(self.route_btn)
        self.pivot_layout_label = QLabel("Вид таблицы:")
        self.pivot_layout_combo = QComboBox()
        self.pivot_layout_combo.addItem("По маршрутам", PIVOT_LAYOUT_BY_ROUTES)
        self.pivot_layout_combo.addItem("Общий свод", PIVOT_LAYOUT_SUMMARY)
        self.pivot_layout_combo.currentIndexChanged.connect(self._on_filters_changed)
        row_filters.addWidget(self.pivot_layout_label)
        row_filters.addWidget(self.pivot_layout_combo)
        row_filters.addStretch()
        row_filters.addWidget(self.apply_btn)
        row_filters.addWidget(self.reset_btn)

        row_period = QHBoxLayout()
        self.from_month = QComboBox()
        self.from_year = QComboBox()
        self.to_month = QComboBox()
        self.to_year = QComboBox()
        self._init_period_combos()

        row_period.addWidget(QLabel("Период с:"))
        row_period.addWidget(self.from_month)
        row_period.addWidget(self.from_year)
        row_period.addWidget(QLabel("по:"))
        row_period.addWidget(self.to_month)
        row_period.addWidget(self.to_year)
        row_period.addStretch()

        main.addLayout(row_filters)
        main.addLayout(row_period)

    def _init_period_combos(self):
        for combo in (self.from_month, self.to_month):
            for key, val in MONTHS_RU.items():
                combo.addItem(val, key)
        for combo in (self.from_year, self.to_year):
            for y in range(2020, 2030):
                combo.addItem(str(y), y)
        # Период не перестраивает отчёт сразу: диапазон задаётся четырьмя
        # комбобоксами, и каждое движение вызывало полный пересчёт — включая
        # промежуточные состояния вроде «с декабря 2025 по январь 2024» (PERF-4).
        for combo in self._period_combos():
            combo.currentIndexChanged.connect(self._on_period_changed)

    def _load_initial_data(self):
        self._load_entities()
        self._load_indicators()
        self._load_route_types()
        self._set_default_period()

    def _load_entities(self, keep_selection: bool = False):
        # Отсева «Все» здесь больше нет: контроллер отдаёт только предприятия
        # (PERF-9). set_items сам оставляет из выбора то, что есть в новом
        # списке, поэтому сохранять выбор отдельно не требуется.
        self.entity_btn.set_items(self.filter_controller.load_entities(self.current_mode))
        if not keep_selection:
            self.entity_btn.clear_selection()

    def _load_indicators(self, keep_selection: bool = False):
        self.indicator_btn.set_items(self.filter_controller.load_indicators())
        if not keep_selection:
            self.indicator_btn.clear_selection()

    def _load_route_types(self):
        self.route_btn.set_items([(rt, rt.value) for rt in RouteType])
        self.route_btn.clear_selection()

    def _set_default_period(self):
        """Умолчание — последний год, за который есть данные.

        Прежде брался весь диапазон, от минимального года до максимального. Пока
        одноимённые месяцы разных лет схлопывались в одну колонку (DATA-1), это и
        был спусковой крючок ошибки — она срабатывала сразу при открытии. Теперь
        колонки раздельные, и тот же диапазон дал бы 24+ колонки на старте.
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
        # Перевёрнутый период отчёт не перестраивает: пустая таблица без причины
        # выглядит как «данных нет», а не как «границы перепутаны» (BUG-16).
        # Отметка «не применено» при этом остаётся — отчёт и правда устарел.
        if not period_is_usable(self, self):
            return
        self._clear_pending()
        self.filters_changed.emit()

    def _clear_pending(self):
        self._period_pending = False
        self.apply_btn.setText(APPLY_CAPTION)

    def reload_reference_lists(self):
        """Перечитать списки предприятий и показателей: после импорта и правки справочников.

        Период и уже сделанный выбор намеренно не трогаются: пользователь их
        выставил, и сброс на умолчание после импорта выглядел бы потерей работы
        (BUG-25). Пропавшие из справочника позиции уходят из выбора сами.
        """
        self._load_entities(keep_selection=True)
        self._load_indicators(keep_selection=True)

    def get_airline_filter_ids(self):
        """None — все АК; иначе список id."""
        if self.current_mode != MODE_AIRLINE:
            return None
        return self.entity_btn.filter_active_ids()

    def get_airport_filter_ids(self):
        if self.current_mode == MODE_AIRLINE:
            return None
        return self.entity_btn.filter_active_ids()

    def get_indicator_filter_ids(self):
        return self.indicator_btn.filter_active_ids()

    def get_route_filter_types(self):
        """Список RouteType или None (все). Только для режима авиакомпаний."""
        if self.current_mode != MODE_AIRLINE:
            return None
        return self.route_btn.filter_active_ids()

    def get_pivot_table_layout(self):
        """Режим свода по одной АК: по маршрутам или общий свод."""
        if self.current_mode != MODE_AIRLINE:
            return None
        d = self.pivot_layout_combo.currentData()
        return d if d else PIVOT_LAYOUT_BY_ROUTES

    def get_from_month(self):
        return self.from_month.currentData()

    def get_from_year(self):
        return self.from_year.currentData()

    def get_to_month(self):
        return self.to_month.currentData()

    def get_to_year(self):
        return self.to_year.currentData()

    def reset_filters(self):
        self.entity_btn.clear_selection()
        self.indicator_btn.clear_selection()
        self.route_btn.clear_selection()
        self.pivot_layout_combo.setCurrentIndex(0)
        self._set_default_period()

