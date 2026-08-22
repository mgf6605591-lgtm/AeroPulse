# forms/models/pivot_dict_model.py
from typing import Any
from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex

from controllers.reports.formulas import NO_FORMULAS, PivotFormulas
from forms.models.formatting import format_number_ru
from forms.models.roles import FORMULA_ROLE, RAW_VALUE_ROLE
from decimal import Decimal


class PivotDictModel(QAbstractTableModel):
    """Модель для сводной (pivot) таблицы. Данные — список словарей (строк)."""

    def __init__(self, data: list[dict] | None = None, headers: list[str] | None = None, keys: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._data = data or []
        self._headers = headers or []
        self._keys = keys or []
        self._formulas = NO_FORMULAS
        self._col_by_key: dict[str, int] = {}

    def set_source_data(
        self,
        data: list[dict],
        headers: list[str],
        keys: list[str],
        formulas: PivotFormulas | None = None,
    ):
        """Установка данных модели.

        Метод назывался `setData` и перекрывал `QAbstractItemModel.setData(index,
        value, role)` — стандартный способ Qt записать значение в ячейку. Общего
        у них было только имя (BUG-12).

        `formulas` — правила построителя о том, какие ячейки сложены из каких.
        Свод, который ничего не складывает, их не передаёт.
        """
        self.beginResetModel()
        self._data = data
        self._headers = headers
        self._keys = keys
        self._formulas = formulas or NO_FORMULAS
        # Правила названы ключами колонок, а спрашивают о ячейке по номеру.
        # Перевод считается один раз на свод, а не на каждый вопрос о ячейке.
        self._col_by_key = {key: col for col, key in enumerate(keys)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r >= len(self._data) or c >= len(self._keys):
            return None
        row = self._data[r]
        key = self._keys[c]
        val = row.get(key)

        if role == RAW_VALUE_ROLE:
            # Значение без форматирования — для выгрузки в XLSX (FUNC-2).
            return val

        if role == FORMULA_ROLE:
            # Из чего ячейка сложена — для формул в выгрузке. Сходится ли сумма,
            # модель не проверяет: это дело того, кто пишет книгу.
            return self._formulas.operands(r, c, key, self._col_by_key) or None

        if role == Qt.ItemDataRole.DisplayRole:
            if val is None or val == "":
                return ""
            if isinstance(val, (int, float, Decimal)):
                return format_number_ru(val)
            return str(val)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if isinstance(val, (int, float, Decimal)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

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

    def get_row(self, row: int) -> dict | None:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None
