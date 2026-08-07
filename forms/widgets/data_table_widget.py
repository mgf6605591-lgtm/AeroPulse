# forms/widgets/data_table_widget.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QPushButton, QTableView, QLabel, QAbstractItemView, QMenu
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from db.models.sqlalchemy_table_model import SQLAlchemyTableModel
from db.models.pivot_dict_model import PivotDictModel
from db.models.multilevel_header import MultiLevelHeaderView
from controllers.data_controller import DataController
from controllers.export_controller import ExportController
from utils.constants import GA12_TOTAL_HEADER, ROUTE_TYPE_NAMES, VIEW_PIVOT, VIEW_DETAIL


class DataTableWidget(QWidget):
    """Виджет таблицы данных"""
    
    delete_requested = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_view = VIEW_PIVOT
        self.current_mode = 1  # MODE_AIRLINE
        self.data_controller = DataController()
        self._init_ui()
        self._setup_models()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # Панель режимов
        mode_box = QGroupBox("Режим отображения")
        mode_layout = QHBoxLayout(mode_box)
        
        self.radio_pivot = QRadioButton("Сводный (pivot)")
        self.radio_pivot.setChecked(True)
        self.radio_pivot.toggled.connect(self._on_view_toggle)
        
        self.radio_detail = QRadioButton("Подробный (с удалением)")
        self.radio_detail.toggled.connect(self._on_view_toggle)
        
        self.delete_btn = QPushButton("Удалить выбранное")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setEnabled(False)
        
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
        self.data_table.setModel(self.pivot_model)
    
    def _on_view_toggle(self):
        """Переключение режима отображения"""
        if self.radio_pivot.isChecked():
            self.current_view = VIEW_PIVOT
            self.data_table.setModel(self.pivot_model)
            self.delete_btn.setEnabled(False)
        else:
            self.current_view = VIEW_DETAIL
            self.data_table.setModel(self.detail_model)
            self.delete_btn.setEnabled(True)
        if hasattr(self, "parent_window"):
            self.parent_window.reload_table_for_widget(self)
    
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
    
    def _set_column_widths_pivot(self, stats: dict, headers: list = None):
        """Устанавливает ширину столбцов для сводной таблицы на основе заголовков"""
        if headers is None:
            return

        if stats.get("layout_ga15"):
            self.data_table.setColumnWidth(0, 400)
            self.data_table.setColumnWidth(1, 72)
            for col in range(2, len(headers)):
                self.data_table.setColumnWidth(col, 108)
            return

        # Словарь соответствия заголовков и ширины
        width_map = {
            'Показатель': 340,
            'Ед. изм.': 110,
            'Код ОКЕИ': 80,
            'Свод': 100,
            'Всего': 100,
            GA12_TOTAL_HEADER: 100,
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
    
    def load_data(self, mode: int, filters: dict):
        """Загрузка данных в таблицу"""
        self.current_mode = mode
        entity_id = None
        if filters.get("airline_id"):
            entity_id = filters["airline_id"]
        elif filters.get("airport_id"):
            entity_id = filters["airport_id"]
        elif filters.get("airline_ids") and len(filters["airline_ids"]) == 1:
            entity_id = filters["airline_ids"][0]
        elif filters.get("airport_ids") and len(filters["airport_ids"]) == 1:
            entity_id = filters["airport_ids"][0]
        
        if self.current_view == VIEW_PIVOT:
            data = self.data_controller.load_pivot_data(mode, filters, entity_id)
            self.pivot_model.setData(data['rows'], data['headers'], data['keys'])
            self.grouped_header.set_groups(data['groups'])
            
            stats = data['stats']
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
                    f"Свод {'АК' if mode == 1 else 'аэропортов'} — показателей: {stats['indicators']}, "
                    f"{'авиакомпаний' if mode == 1 else 'аэропортов'}: {stats.get('airlines', stats.get('airports', 0))}"
                )
            
            # Установка ширины столбцов для сводной таблицы
            self._set_column_widths_pivot(stats, data['headers'])
            
        else:
            data = self.data_controller.load_detail_data(mode, filters)
            self.detail_model.setHeaders(data['headers'])
            self.detail_model.setColumnAttributes(data['attrs'])
            self.detail_model.setData(data['records'])
            self.grouped_header.set_groups([])
            self.data_count_label.setText(f"Записей: {len(data['records'])}")
            
            # Установка ширины столбцов для подробной таблицы
            self._set_column_widths_detail(data['headers'])
    
    def get_table_view(self) -> QTableView:
        """Возвращает виджет таблицы"""
        return self.data_table

    def get_header_groups_for_export(self) -> list:
        """Группы заголовка (как на экране) для экспорта; для сводной таблицы с группами месяцев."""
        return self.grouped_header.get_groups()
    
    def set_parent_window(self, parent):
        """Устанавливает родительское окно для доступа к методам"""
        self.parent_window = parent