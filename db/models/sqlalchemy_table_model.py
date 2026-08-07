from typing import List, Any, Optional
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PyQt6.QtGui import QColor
from decimal import Decimal

from db.models.roles import RAW_VALUE_ROLE


class SQLAlchemyTableModel(QAbstractTableModel):
    """
    Универсальная модель для отображения списка SQLAlchemy объектов в QTableView
    """

    def __init__(self, data: List[Any] = None, headers: List[str] = None, parent=None):
        super().__init__(parent)
        self._data = data or []
        self._headers = headers or []
        self._column_attrs = []

    def setData(self, data: List[Any]):
        """Установка данных модели"""
        self.beginResetModel()
        self._data = data
        self.endResetModel()

    def setHeaders(self, headers: List[str]):
        """Установка заголовков колонок"""
        self._headers = headers

    def setColumnAttributes(self, attrs: List[str]):
        """
        Установка соответствия колонок атрибутам моделей
        Например: ['id', 'name', 'value']
        """
        self._column_attrs = attrs

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole) -> Any:
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if row >= len(self._data) or col >= len(self._headers):
            return None

        obj = self._data[row]

        if role == RAW_VALUE_ROLE:
            # Значение без приведения к строке — для выгрузки в XLSX (FUNC-2).
            # Числа уходят числами, у перечислений берётся подпись.
            if self._column_attrs and col < len(self._column_attrs):
                value = self._get_nested_attribute(obj, self._column_attrs[col])
                if hasattr(value, 'value'):
                    return value.value
                return value
            return str(obj)

        if role == Qt.ItemDataRole.DisplayRole:
            if self._column_attrs and col < len(self._column_attrs):
                attr_name = self._column_attrs[col]
                value = self._get_nested_attribute(obj, attr_name)
                if value is None:
                    return ""
                # Для enum показываем value
                if hasattr(value, 'value'):
                    return str(value.value)
                return str(value)
            return str(obj)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if self._is_numeric_column(obj, col):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ToolTipRole:
            if self._column_attrs and col < len(self._column_attrs):
                value = self._get_nested_attribute(obj, self._column_attrs[col])
                if value:
                    return f"{self._headers[col]}: {value}"

        return None

    def _get_nested_attribute(self, obj: Any, attr_path: str) -> Any:
        """Получение значения по пути атрибута (поддержка вложенных отношений)"""
        try:
            value = obj
            for attr in attr_path.split('.'):
                value = getattr(value, attr, None)
                if value is None:
                    return None
            return value
        except (AttributeError, TypeError):
            return None

    def _is_numeric_column(self, obj: Any, col: int) -> bool:
        if self._column_attrs and col < len(self._column_attrs):
            value = self._get_nested_attribute(obj, self._column_attrs[col])
            return isinstance(value, (int, float, Decimal))
        return False

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole) -> Any:
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
        self.beginResetModel()
        self.endResetModel()
