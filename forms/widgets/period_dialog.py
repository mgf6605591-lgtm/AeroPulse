# forms/widgets/period_dialog.py
from datetime import date

from forms.widgets.dialog_buttons import set_caption
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox
)

from utils.constants import MONTHS_LIST, MONTHS_RU


class PeriodDialog(QDialog):
    """Запрос отчётного периода для файла, в котором его не удалось определить.

    Показывается вместо прежней молчаливой подстановки «январь 2025». Придуманный
    за пользователя период не оставался безобидной пометкой: импорт работает как
    upsert по ключу (показатель, рейс, месяц, год), поэтому данные чужого месяца
    затирали настоящую январскую отчётность без резервной копии (DATA-2).
    """

    def __init__(self, file_name: str, month: str | None = None,
                 year: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Отчётный период не определён")
        self.setMinimumWidth(420)
        self._init_ui(file_name, month, year)

    def _init_ui(self, file_name: str, month: str | None, year: int | None) -> None:
        layout = QFormLayout(self)

        info = QLabel(
            f"В файле «{file_name}» не удалось прочитать отчётный период "
            "(лист «Титул», ячейка D13).\n"
            "Укажите период вручную — иначе файл импортирован не будет."
        )
        info.setWordWrap(True)
        layout.addRow(info)

        self.month_combo = QComboBox()
        for name in MONTHS_LIST:
            self.month_combo.addItem(MONTHS_RU[name], name)
        # Если из файла удалось прочитать половину периода (например, месяц без
        # года), она подставляется — но подтвердить её всё равно должен человек.
        if month in MONTHS_LIST:
            self.month_combo.setCurrentIndex(MONTHS_LIST.index(month))
        layout.addRow("Месяц:", self.month_combo)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(1990, 2100)
        self.year_spin.setValue(int(year) if year else date.today().year)
        layout.addRow("Год:", self.year_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        set_caption(buttons, QDialogButtonBox.StandardButton.Cancel, "Пропустить файл")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_month(self) -> str:
        """Возвращает Months.name выбранного месяца."""
        return self.month_combo.currentData()

    def get_year(self) -> int:
        return self.year_spin.value()
