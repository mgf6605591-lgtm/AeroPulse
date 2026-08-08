# forms/models/sqlalchemy_table_model.py
from typing import List, Any, Optional
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from decimal import Decimal

from forms.models.formatting import format_number_ru
from forms.models.roles import RAW_VALUE_ROLE


class SQLAlchemyTableModel(QAbstractTableModel):
    """
    Универсальная модель для отображения списка объектов-строк в QTableView
    """

    def __init__(self, data: List[Any] = None, headers: List[str] = None, parent=None):
        super().__init__(parent)
        self._data = data or []
        self._headers = headers or []
        self._attr_paths: List[List[str]] = []
        self._numeric_columns: set[int] = set()

    def set_source_data(self, data: List[Any]):
        """Установка данных модели.

        Метод назывался `setData` и перекрывал `QAbstractItemModel.setData(index,
        value, role)` — стандартный способ Qt записать значение в ячейку.
        Совпадали только имена: делегат, `QDataWidgetMapper` или включённое
        редактирование позвали бы его с индексом вместо списка записей (BUG-12).
        """
        self.beginResetModel()
        self._data = data
        self._rebuild_numeric_columns()
        self.endResetModel()

    def setHeaders(self, headers: List[str]):
        """Установка заголовков колонок"""
        self._headers = headers

    def setColumnAttributes(self, attrs: List[str]):
        """
        Установка соответствия колонок атрибутам моделей
        Например: ['id', 'name', 'value']
        """
        # Путь разбирается один раз на колонку, а не на каждое обращение к ячейке:
        # `'a.b.c'.split('.')` в отрисовке — это разбор строки на каждую видимую
        # ячейку при каждой перерисовке (PERF-7).
        self._attr_paths = [attr.split('.') for attr in attrs]
        self._rebuild_numeric_columns()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if row >= len(self._data) or col >= len(self._headers):
            return None

        # Выравнивание берётся из состава колонки, а не из типа значения в самой
        # ячейке: тип одинаков по всей колонке, а вычислялся он для каждой ячейки
        # заново — со всей цепочкой getattr — при каждой перерисовке (PERF-7).
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in self._numeric_columns:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role not in (RAW_VALUE_ROLE, Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None

        obj = self._data[row]
        if not self._attr_paths or col >= len(self._attr_paths):
            return str(obj) if role != Qt.ItemDataRole.ToolTipRole else None
        value = self._get_attribute(obj, self._attr_paths[col])

        if role == RAW_VALUE_ROLE:
            # Значение без приведения к строке — для выгрузки в XLSX (FUNC-2).
            # Числа уходят числами, у перечислений берётся подпись.
            if hasattr(value, 'value'):
                return value.value
            return value

        if role == Qt.ItemDataRole.DisplayRole:
            if value is None:
                return ""
            # Для enum показываем value
            if hasattr(value, 'value'):
                return str(value.value)
            if isinstance(value, (float, Decimal)):
                # Форматируются только дробные величины. Целое здесь — это `id` и
                # год, и разряды в них разделять нельзя: «2 025» не год (BUG-26).
                return format_number_ru(value)
            return str(value)

        # ToolTipRole. Сравнение именно с None: `if value` считает ложью и ноль, и
        # `Decimal('0')` — а ноль в отчётности не редкость, а норма, и подсказка
        # пропадала как раз у него (BUG-29).
        if value is not None:
            return f"{self._headers[col]}: {value}"
        return None

    def _rebuild_numeric_columns(self):
        """Определяет числовые колонки — один раз на загрузку данных.

        Решает первое непустое значение колонки: состав колонки задан набором
        полей записи и по строкам не меняется.
        """
        self._numeric_columns = set()
        for col, path in enumerate(self._attr_paths):
            for obj in self._data:
                value = self._get_attribute(obj, path)
                if value is None:
                    continue
                if isinstance(value, (int, float, Decimal)):
                    self._numeric_columns.add(col)
                break

    def _get_attribute(self, obj: Any, path: List[str]) -> Any:
        """Значение по заранее разобранному пути (поддержка вложенных отношений)"""
        try:
            value = obj
            for attr in path:
                value = getattr(value, attr, None)
                if value is None:
                    return None
            return value
        except (AttributeError, TypeError):
            return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section < len(self._headers):
                return self._headers[section]

        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(section + 1)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def get_object_by_row(self, row: int) -> Optional[Any]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def refresh(self, new_data: List[Any] = None):
        if new_data is not None:
            self._data = new_data
            self._rebuild_numeric_columns()
        self.beginResetModel()
        self.endResetModel()
