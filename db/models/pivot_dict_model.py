from typing import List, Dict, Any, Optional
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from decimal import Decimal


class PivotDictModel(QAbstractTableModel):
    """Модель для сводной (pivot) таблицы. Данные — список словарей (строк)."""

    def __init__(self, data: List[Dict] = None, headers: List[str] = None, keys: List[str] = None, parent=None):
        super().__init__(parent)
        self._data = data or []
        self._headers = headers or []
        self._keys = keys or []

    def setData(self, data: List[Dict], headers: List[str], keys: List[str]):
        self.beginResetModel()
        self._data = data
        self._headers = headers
        self._keys = keys
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole) -> Any:
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r >= len(self._data) or c >= len(self._keys):
            return None
        row = self._data[r]
        key = self._keys[c]
        val = row.get(key)

        if role == Qt.ItemDataRole.DisplayRole:
            if val is None or val == "":
                return ""
            if isinstance(val, (int, float, Decimal)):
                if isinstance(val, Decimal):
                    val = float(val)
                # Целочисленное отображение для целых
                if isinstance(val, float) and val == int(val):
                    return f"{int(val):,}".replace(",", " ")
                return f"{val:,.2f}".replace(",", " ")
            return str(val)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if isinstance(val, (int, float, Decimal)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

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

    def get_row(self, row: int) -> Optional[Dict]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None
