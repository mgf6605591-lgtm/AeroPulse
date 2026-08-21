# forms/widgets/data_table_widget.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QPushButton, QTableView, QLabel, QAbstractItemView, QMenu
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from forms.models.sqlalchemy_table_model import SQLAlchemyTableModel
from forms.models.pivot_dict_model import PivotDictModel
from forms.widgets.multilevel_header import MultiLevelHeaderView
from controllers.data_controller import DataController
from controllers.export_header import ExportHeader, build_export_header
from controllers.report_filters import NO_FILTERS, ReportFilters
from utils.constants import (
    GA12_GRAND_TOTAL_HEADER,
    GA12_TOTAL_HEADER,
    MODE_AIRLINE,
    ROUTE_TYPE_NAMES,
    VIEW_DETAIL,
    VIEW_PIVOT,
)


# Причины, по которым удалять сейчас нечего. Показываются подсказкой на самой
# кнопке: недоступное действие остаётся видимым и объясняет, чего ему не хватает.
REASON_PIVOT = "Удаление доступно в подробном режиме: в сводной таблице строка — это сумма, а не запись."
REASON_NO_SELECTION = "Выделите строки, которые нужно удалить."


class DataTableWidget(QWidget):
    """Виджет таблицы данных"""

    delete_requested = pyqtSignal(list)
    # О смене режима отображения виджет сообщает сигналом, как и об удалении.
    # Прежде он звал метод родителя напрямую, а зависимость устанавливалась
    # постфактум через `set_parent_window()` и проверялась `hasattr` (ARCH-10).
    reload_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_view = VIEW_PIVOT
        self.current_mode = MODE_AIRLINE
        self.data_controller = DataController()
        # Чем описать выгрузку, знает тот, кто загрузил данные. Экран показывает
        # предприятие и период в строке под таблицей, а в файл они не попадали
        # вовсе (FUNC-4) — теперь показанное запоминается для шапки книги.
        self._last_filters: ReportFilters = NO_FILTERS
        self._last_stats: dict = {}
        self._init_ui()
        self._setup_models()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # Панель режимов
        mode_box = QGroupBox("Режим отображения")
        mode_layout = QHBoxLayout(mode_box)
        
        self.radio_pivot = QRadioButton("Сводный (pivot)")
        self.radio_pivot.setChecked(True)

        self.radio_detail = QRadioButton("Подробный (с удалением)")
        # Сигнал подключён только к одной кнопке: `toggled` испускается и у
        # включаемой, и у выключаемой, поэтому подписка на обе давала два вызова
        # на один клик — и две полных перезагрузки отчёта (BUG-24).
        self.radio_detail.toggled.connect(self._on_view_toggle)
        
        self.delete_btn = QPushButton("Удалить выбранное")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setToolTip(REASON_PIVOT)

        mode_layout.addWidget(self.radio_pivot)
        mode_layout.addWidget(self.radio_detail)
        mode_layout.addStretch()
        mode_layout.addWidget(self.delete_btn)
        layout.addWidget(mode_box)
        
        # Таблица
        self.data_table = QTableView()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSortingEnabled(False)
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.data_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.data_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.data_table.customContextMenuRequested.connect(self._on_context_menu)
        
        self.grouped_header = MultiLevelHeaderView(self.data_table)
        self.data_table.setHorizontalHeader(self.grouped_header)
        self.grouped_header.setStretchLastSection(True)
        layout.addWidget(self.data_table)
        
        # Shortcut для Delete — только при фокусе внутри своей таблицы.
        # Контекст по умолчанию (WindowShortcut) означал бы, что в окне
        # зарегистрированы два одинаковых шортката (вкладки а/к и аэропортов) —
        # Qt считает такую пару неоднозначной и не вызывает ни один обработчик
        # (BUG-21), — а до того Delete срабатывал бы из полей фильтров,
        # где его нажимают, чтобы стереть символ (BUG-22).
        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self.data_table)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.delete_shortcut.activated.connect(self._on_delete_clicked)
        
        # Счетчик записей
        self.data_count_label = QLabel("")
        layout.addWidget(self.data_count_label)
    
    def _setup_models(self):
        """Инициализация моделей данных"""
        self.pivot_model = PivotDictModel()
        self.detail_model = SQLAlchemyTableModel()
        self.data_controller.set_models(self.pivot_model, self.detail_model)
        self._set_table_model(self.pivot_model)

    def _set_table_model(self, model):
        """Меняет модель таблицы и пересоздаёт подписку на выделение.

        `setModel()` заводит таблице новую модель выделения и выбрасывает
        прежнюю вместе с подписками, поэтому подключаться к ней нужно после
        каждой смены, а не один раз в конструкторе.
        """
        self.data_table.setModel(model)
        selection = self.data_table.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._sync_delete_button)
        self._sync_delete_button()

    def _sync_delete_button(self, *_args):
        """Доступность кнопки удаления и причина, по которой она недоступна.

        Прежде кнопка включалась по одному только режиму: в подробном она была
        нажимаема всегда, а нажатие без выделенных строк не делало ничего и
        ничего не объясняло.
        """
        if self.current_view != VIEW_DETAIL:
            self.delete_btn.setEnabled(False)
            self.delete_btn.setToolTip(REASON_PIVOT)
            return

        selection = self.data_table.selectionModel()
        selected = selection.selectedRows() if selection is not None else []
        self.delete_btn.setEnabled(bool(selected))
        self.delete_btn.setToolTip("" if selected else REASON_NO_SELECTION)

    def _on_view_toggle(self):
        """Переключение режима отображения"""
        if self.radio_pivot.isChecked():
            self.current_view = VIEW_PIVOT
            self._set_table_model(self.pivot_model)
        else:
            self.current_view = VIEW_DETAIL
            self._set_table_model(self.detail_model)
        self.reload_requested.emit()

    def _on_context_menu(self, pos):
        """Контекстное меню"""
        if self.current_view != VIEW_DETAIL:
            return
        idx = self.data_table.indexAt(pos)
        if not idx.isValid():
            return
        menu = QMenu(self)
        delete_act = QAction("Удалить запись", self)
        delete_act.triggered.connect(self._on_delete_clicked)
        menu.addAction(delete_act)
        menu.exec(self.data_table.viewport().mapToGlobal(pos))
    
    def _on_delete_clicked(self):
        """Обработчик удаления"""
        if self.current_view != VIEW_DETAIL:
            return
        
        selection = self.data_table.selectionModel().selectedRows()
        if not selection:
            return
        
        ids_to_delete = []
        for index in selection:
            obj = self.detail_model.get_object_by_row(index.row())
            if obj:
                ids_to_delete.append(obj.id)
        
        if ids_to_delete:
            self.delete_requested.emit(ids_to_delete)
    
    def _set_column_widths_pivot(self, stats: dict, headers: list | None = None):
        """Устанавливает ширину столбцов для сводной таблицы на основе заголовков"""
        if headers is None:
            return

        if stats.get("layout_ga15"):
            self.data_table.setColumnWidth(0, 400)
            self.data_table.setColumnWidth(1, 72)
            for col in range(2, len(headers)):
                self.data_table.setColumnWidth(col, 108)
            return

        if stats.get("layout_ga15_summary"):
            # Первая колонка — название аэропорта, дальше одиннадцать граф бланка
            # на каждый период: узкие и одинаковые, чтобы периоды читались подряд.
            self.data_table.setColumnWidth(0, 280)
            for col in range(1, len(headers)):
                self.data_table.setColumnWidth(col, 104)
            return

        # Словарь соответствия заголовков и ширины
        width_map = {
            'Показатель': 340,
            'Ед. изм.': 110,
            'Код ОКЕИ': 80,
            'Свод': 100,
            'Всего': 100,
            GA12_TOTAL_HEADER: 100,
            GA12_GRAND_TOTAL_HEADER: 110,
        }

        # Типы маршрутов для одной авиакомпании. Подписи берутся из констант, а не
        # повторяются здесь: иначе после правки заголовка ширина молча переставала
        # применяться, а разъехавшиеся колонки списывали бы на длину названия.
        route_widths = {
            ROUTE_TYPE_NAMES['trunk']: 140,
            ROUTE_TYPE_NAMES['local']: 150,
            ROUTE_TYPE_NAMES['interregional']: 130,
            ROUTE_TYPE_NAMES['subsidir']: 170,
        }
        
        for col, header in enumerate(headers):
            # Проверяем по точному совпадению
            if header in width_map:
                width = width_map[header]
            # Проверяем для маршрутов
            elif header in route_widths:
                width = route_widths[header]
            # Для названий авиакомпаний/аэропортов
            elif len(header) > 20:
                width = 180
            elif len(header) > 10:
                width = 140
            else:
                width = 100
            
            self.data_table.setColumnWidth(col, width)
    
    def _set_column_widths_detail(self, headers: list):
        """Устанавливает ширину столбцов для подробной таблицы на основе заголовков"""
        # Словарь соответствия заголовков и ширины для подробной таблицы
        detail_width_map = {
            'ID': 50,
            'Авиакомпания': 200,
            'Код а/к': 80,
            'Показатель': 250,
            'Месяц': 100,
            'Год': 60,
            'Значение': 120,
            'Ед. изм.': 100,
            'Тип маршрута': 150,
            'Регулярность': 190,
            'Аэропорт': 200,
            'Код': 80,
            'Нас. пункт': 150,
        }
        
        for col, header in enumerate(headers):
            if header in detail_width_map:
                width = detail_width_map[header]
            elif len(header) > 20:
                width = 180
            elif len(header) > 10:
                width = 120
            else:
                width = 100
            
            self.data_table.setColumnWidth(col, width)
    
    def load_data(self, mode: int, filters: ReportFilters):
        """Загрузка данных в таблицу"""
        self.current_mode = mode
        # Четыре ветки подряд отвечали на один вопрос — какое предприятие
        # выбрано, если оно одно. Теперь это одно производное значение (ARCH-5).
        entity_id = filters.entity_id

        self._last_filters = filters

        if self.current_view == VIEW_PIVOT:
            data = self.data_controller.load_pivot_data(mode, filters, entity_id)
            self.pivot_model.set_source_data(data['rows'], data['headers'], data['keys'])
            self.grouped_header.set_groups(data['groups'])
            
            stats = data['stats']
            self._last_stats = dict(stats)
            if 'airline_name' in stats:
                self.data_count_label.setText(
                    f"{stats['airline_name']} — показателей: {stats['indicators']}, месяцев: {stats['months']}"
                )
            elif stats.get("pivot_multi_airline_routes"):
                self.data_count_label.setText(
                    f"Свод по маршрутам — авиакомпаний: {stats.get('airlines', 0)}, "
                    f"показателей: {stats['indicators']}, месяцев: {stats.get('months', 0)}, "
                    f"записей: {stats.get('records', 0)}"
                )
            elif stats.get("layout_ga15_summary"):
                self.data_count_label.setText(
                    f"Сводка 15-ГА — аэропортов: {stats.get('airports', 0)}, "
                    f"из них предприятий с разбивкой: {stats.get('enterprises', 0)}, "
                    f"периодов: {stats.get('periods', 0)}, "
                    f"записей в выборке: {stats.get('records', 0)}"
                )
            elif stats.get("layout_ga15"):
                an = stats.get("airport_name") or "Аэропорт"
                self.data_count_label.setText(
                    f"{an} — форма 15-ГА; строк показателей: {stats.get('indicators', 0)}, "
                    f"записей в выборке: {stats['records']}"
                )
            elif 'airport_name' in stats:
                self.data_count_label.setText(
                    f"{stats['airport_name']} — показателей: {stats['indicators']}"
                )
            else:
                self.data_count_label.setText(
                    f"Свод {'АК' if mode == MODE_AIRLINE else 'аэропортов'} — показателей: {stats['indicators']}, "
                    f"{'авиакомпаний' if mode == MODE_AIRLINE else 'аэропортов'}: "
                    f"{stats.get('airlines', stats.get('airports', 0))}"
                )
            
            # Установка ширины столбцов для сводной таблицы
            self._set_column_widths_pivot(stats, data['headers'])
            
        else:
            data = self.data_controller.load_detail_data(mode, filters)
            self.detail_model.setHeaders(data['headers'])
            self.detail_model.setColumnAttributes(data['attrs'])
            self.detail_model.set_source_data(data['records'])
            self.grouped_header.set_groups([])
            # У подробной таблицы своего свода нет: считаем то, что в ней лежит.
            self._last_stats = {"records": len(data['records'])}
            self.data_count_label.setText(f"Записей: {len(data['records'])}")
            
            # Установка ширины столбцов для подробной таблицы
            self._set_column_widths_detail(data['headers'])

        # Перезагрузка снимает выделение — значит, удалять снова нечего.
        self._sync_delete_button()

    def get_table_view(self) -> QTableView:
        """Возвращает виджет таблицы"""
        return self.data_table

    def get_header_groups_for_export(self) -> list:
        """Группы заголовка (как на экране) для экспорта; для сводной таблицы с группами месяцев."""
        return self.grouped_header.get_groups()

    def export_header(self, user: str | None = None) -> ExportHeader:
        """Шапка книги: форма, предприятие, период, счётчики, момент выгрузки."""
        return build_export_header(
            mode=self.current_mode,
            view=self.current_view,
            filters=self._last_filters,
            stats=self._last_stats,
            user=user,
        )
