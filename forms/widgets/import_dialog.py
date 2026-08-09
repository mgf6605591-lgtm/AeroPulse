# forms/widgets/import_dialog.py
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QMessageBox
)


# Признак того, что предприятие названо в самом файле. Отчёт 12-ГА называет свою
# авиакомпанию в титуле, отдельный бланк 15-ГА — свой аэропорт в шапке, а сводный
# бланк перечисляет тридцать с лишним аэропортов сразу, и выбрать из них одно
# нельзя. Значение непустое намеренно: `accept()` не пропускает элементы без
# данных, потому что ими выглядят строки, набранные в поле руками (BUG-19).
ENTITY_FROM_FILE = "from_file"


class ImportDialog(QDialog):
    """Диалог выбора параметров импорта"""

    # Список предприятий заполняет тот, кто знает про базу. Прежде диалог звал
    # метод родителя через `hasattr(self, 'parent')` — проверку, истинную у
    # любого QObject, потому что `parent` это метод (ARCH-10).
    type_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры импорта")
        self.setMinimumWidth(380)
        self._init_ui()
    
    def _init_ui(self):
        layout = QFormLayout(self)
        
        # Выбор типа предприятия
        self.type_combo = QComboBox()
        self.type_combo.addItem("Авиакомпания", "airline")
        self.type_combo.addItem("Аэропорт", "airport")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addRow("Тип предприятия:", self.type_combo)
        
        # Выбор предприятия
        self.entity_combo = QComboBox()
        self.entity_combo.setEditable(True)
        self.entity_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        layout.addRow("Предприятие:", self.entity_combo)
        
        # Информационная метка
        info = QLabel(
            "«Предприятие из файла» — отчёт называет его сам: в титуле XML "
            "или в шапке бланка.\n"
            "Месяц и год берутся из файла: лист «Титул», ячейка D13 — в Excel; "
            "период отчёта или\nхвост имени файла (…_2025_1.xml) — в XML. "
            "Если период прочитать не удалось,\nпрограмма спросит его отдельно "
            "по каждому такому файлу."
        )
        info.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(info)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def _on_type_changed(self):
        """Тип сменился: список предприятий устарел и ждёт нового."""
        self.entity_combo.clear()
        self.entity_combo.setEnabled(False)
        self.type_changed.emit(self.get_type())
    
    def select_type(self, entity_type: str) -> None:
        """Ставит тип предприятия — по вкладке, с которой позвали импорт (FUNC-12).

        Диалог всегда открывался на «Авиакомпании» независимо от вкладки: с
        вкладки аэропортов пользователь получал список авиакомпаний, и, не
        заметив этого, упирался в отказ по несовпадению формы (DATA-6).

        Сигнал смены типа на время выбора глушится, а список предприятий
        заполняет вызывающий. Иначе выходило несимметрично: при выборе
        «Аэропорта» срабатывал `_on_type_changed` и список читался дважды, а при
        «Авиакомпании» Qt сигнала не слал вовсе — тип и так стоял первым.
        """
        index = self.type_combo.findData(entity_type)
        if index < 0:
            return
        self.type_combo.blockSignals(True)
        try:
            self.type_combo.setCurrentIndex(index)
        finally:
            self.type_combo.blockSignals(False)
    
    def accept(self):
        """Пропускает дальше только предприятие, действительно выбранное из списка.

        Комбобокс редактируемый ради поиска набором с клавиатуры, но при вводе
        названия, которого в списке нет, currentIndex остаётся на прежнем элементе:
        get_entity_id() возвращал ID ранее выбранного предприятия, а пользователь
        видел набранный им текст — и отчёт уходил в чужую отчётность (BUG-19).
        """
        text = self.entity_combo.currentText().strip()
        index = self.entity_combo.findText(text, Qt.MatchFlag.MatchFixedString)
        if index < 0 or self.entity_combo.itemData(index) is None:
            QMessageBox.warning(
                self,
                "Предприятие не выбрано",
                f"«{text}» нет в списке предприятий.\n\n"
                "Выберите предприятие из списка: импорт возможен только в то, "
                "которое уже заведено в справочнике."
                if text else
                "Выберите предприятие из списка.",
            )
            return
        # Текст и выбранный элемент приводятся в соответствие, чтобы ID и название
        # дальше по цепочке относились к одному и тому же предприятию.
        self.entity_combo.setCurrentIndex(index)
        super().accept()

    def get_type(self) -> str:
        """Возвращает тип предприятия ('airline' или 'airport')"""
        return self.type_combo.currentData()
    
    def get_entity_id(self) -> int:
        """ID выбранного предприятия; None — предприятие берётся из файла."""
        data = self.entity_combo.currentData()
        return None if data == ENTITY_FROM_FILE else data

    def entity_from_file(self) -> bool:
        """Выбран ли пункт «предприятие из файла»."""
        return self.entity_combo.currentData() == ENTITY_FROM_FILE
