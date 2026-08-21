# forms/widgets/record_edit_dialog.py
"""Правка отчётной строки: значение и период.

Что правится, а что показано только для чтения, решено не здесь: показатель,
предприятие и рейс — это то, чем запись является, а не её свойства (см.
`services/edit_service.py`). Поэтому они стоят в диалоге подписями: человеку
надо видеть, какую именно строку он правит, — но менять их значило бы завести
другую строку вместо этой.

Значение вводится текстом, а не `QDoubleSpinBox`: `float` теряет точность на
десятичных дробях, а вся отчётность держится на том, что этого приведения нет
(см. db/models/types.py). Разбор — `parse_number_ru`, тот же вид записи, в каком
значение показано в таблице.
"""
from decimal import Decimal

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
)

from controllers.detail_rows import DetailRow
from db.models.enums import Months
from forms.models.formatting import parse_number_ru
from forms.widgets.dialog_buttons import set_caption

# Год отчётности: те же границы, что и в диалоге периода при импорте.
YEAR_MIN = 1990
YEAR_MAX = 2100


class RecordEditDialog(QDialog):
    """Окно правки одной записи подробной таблицы."""

    def __init__(self, row: DetailRow, parent=None):
        super().__init__(parent)
        self._row = row
        self.setWindowTitle(f"Правка записи № {row.id}")
        self.setMinimumWidth(460)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QFormLayout(self)

        for caption, text in self._readonly_fields():
            value = QLabel(text)
            value.setWordWrap(True)
            layout.addRow(caption, value)

        self.month_combo = QComboBox()
        for month in Months:
            self.month_combo.addItem(month.value, month)
        if self._row.month is not None:
            self.month_combo.setCurrentIndex(list(Months).index(self._row.month))
        layout.addRow("Месяц:", self.month_combo)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(YEAR_MIN, YEAR_MAX)
        self.year_spin.setValue(self._row.year or YEAR_MIN)
        layout.addRow("Год:", self.year_spin)

        self.value_edit = QLineEdit(_value_text(self._row.value))
        self.value_edit.selectAll()
        layout.addRow("Значение:", self.value_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        set_caption(buttons, QDialogButtonBox.StandardButton.Save, "Сохранить")
        set_caption(buttons, QDialogButtonBox.StandardButton.Cancel, "Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _readonly_fields(self) -> list[tuple[str, str]]:
        """Чем запись опознаётся. Пустые графы не показываются вовсе.

        Набор разный у двух форм: у 12-ГА строка описывается рейсом (вид маршрута
        и регулярность), у 15-ГА — населённым пунктом аэропорта.
        """
        row = self._row
        fields = [
            ("Предприятие:", f"{row.entity_name} ({row.entity_code})".strip()),
            ("Показатель:", row.indicator),
            ("Ед. изм.:", row.measure),
            ("Тип маршрута:", row.route_type.value if row.route_type else ""),
            ("Регулярность:", row.regularity.value if row.regularity else ""),
            ("Нас. пункт:", row.locality or ""),
        ]
        return [(caption, text) for caption, text in fields if text]

    # --- то, что ввели ------------------------------------------------------

    def month(self) -> Months:
        return self.month_combo.currentData()

    def year(self) -> int:
        return self.year_spin.value()

    def value(self) -> Decimal:
        """Введённое значение. Звать после `accept()`: до него оно может не разбираться."""
        return parse_number_ru(self.value_edit.text())

    def accept(self) -> None:
        """Закрывается только с разбираемым значением.

        Иначе окно закрылось бы «успешно», а правка сорвалась бы уже за его
        пределами — там, где показать, какое поле поправить, уже не на чем.
        """
        try:
            self.value()
        except ValueError as error:
            QMessageBox.warning(self, "Значение не понято", str(error))
            self.value_edit.setFocus()
            self.value_edit.selectAll()
            return
        super().accept()


def _value_text(value: Decimal | None) -> str:
    """Значение для правки — всеми знаками, какие есть в базе.

    В таблице оно показано округлённым до сотых (`format_number_ru`), и подставить
    сюда показанное значило бы терять младшие разряды при каждой правке соседнего
    поля. Запятая — как в таблице; `parse_number_ru` принимает и её, и точку.
    """
    if value is None:
        return ""
    return format(value, "f").replace(".", ",")
