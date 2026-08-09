# forms/widgets/airport_filter_widget.py
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
from forms.widgets.period_selector import PeriodSelectorMixin
from utils.constants import APPLY_CAPTION, MODE_AIRPORT


class AirportFilterWidget(PeriodSelectorMixin, QGroupBox):
    """Фильтры вкладки аэропортов: аэропорты, показатели, период.

    Аэропорты выбираются множественно — той же кнопкой, что и авиакомпании на
    соседней вкладке. Пустой выбор означает «все»: вкладка открывается сводкой по
    всем аэропортам, а не приглашением выбрать один. Прежде здесь стоял
    выпадающий список с единственным выбором, и до первого выбора вкладка не
    показывала ничего.
    """

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
        self.airport_btn = MultiSelectFilterButton("Аэропорты")
        self.airport_btn.setMinimumWidth(240)
        self.airport_btn.selectionChanged.connect(self._on_filters_changed)

        self.indicator_btn = MultiSelectFilterButton("Показатели")
        self.indicator_btn.setMinimumWidth(200)
        self.indicator_btn.selectionChanged.connect(self._on_filters_changed)

        self.apply_btn = QPushButton(APPLY_CAPTION)
        self.apply_btn.clicked.connect(self._on_apply)
        self.reset_btn = QPushButton("Сбросить")
        self.reset_btn.clicked.connect(self.reset_requested.emit)

        row_filters.addWidget(QLabel("Аэропорт:"))
        row_filters.addWidget(self.airport_btn)
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

    def _load_lists(self):
        """Первое заполнение: справочники и период по умолчанию."""
        self._load_airports()
        self._load_indicators()
        self._set_default_period()

    def _load_airports(self, keep_selection: bool = False):
        # set_items оставляет из выбора только то, что есть в новом списке,
        # поэтому сохранять выбор отдельно не требуется.
        self.airport_btn.set_items(self.filter_controller.load_entities(MODE_AIRPORT))
        if not keep_selection:
            self.airport_btn.clear_selection()

    def _load_indicators(self, keep_selection: bool = False):
        # set_items оставляет из выбора только то, что есть в новом списке.
        self.indicator_btn.set_items(self.filter_controller.load_indicators())
        if not keep_selection:
            self.indicator_btn.clear_selection()

    def _on_filters_changed(self):
        self.filters_changed.emit()

    def _on_apply(self):
        # Перевёрнутый период отчёт не перестраивает: пустая таблица без причины
        # выглядит как «данных нет», а не как «границы перепутаны» (BUG-16).
        # Отметка «не применено» при этом остаётся — отчёт и правда устарел.
        if not period_is_usable(self, self):
            return
        self._clear_pending()
        self.filters_changed.emit()

    def get_airport_filter_ids(self):
        """None — все аэропорты (сводка); иначе список id."""
        return self.airport_btn.filter_active_ids()

    def get_indicator_filter_ids(self):
        return self.indicator_btn.filter_active_ids()

    def reset_filters(self):
        self.airport_btn.clear_selection()
        self.indicator_btn.clear_selection()
        # Сброс возвращает то же умолчание, что и первое открытие.
        self._set_default_period()

    def reload_reference_lists(self):
        """Перечитать справочники, сохранив выбор аэропорта, показателей и период.

        Прежний метод вызывал `_load_lists()` целиком: он честно возвращал
        выбранные аэропорты, но молча сбрасывал период на умолчание и снимал
        фильтр показателей, хотя обновить требовалось только справочники (BUG-25).
        Сброс кеша здесь не делается — он общий и сбрасывается один раз тем, кто
        менял данные (BUG-7).
        """
        self._load_airports(keep_selection=True)
        self._load_indicators(keep_selection=True)
