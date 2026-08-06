# forms/widgets/import_dialog.py
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QMessageBox
)


class ImportDialog(QDialog):
    """Диалог выбора параметров импорта"""
    
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
            "Месяц и год для каждого файла берутся с листа «Титул», ячейка D13.\n"
            "Если период прочитать не удалось, программа спросит его отдельно "
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
        """Обработчик изменения типа предприятия"""
        self.entity_combo.clear()
        self.entity_combo.setEnabled(False)
        # Сигнал для родительского окна о необходимости обновить список
        if hasattr(self, 'parent') and hasattr(self.parent(), 'refresh_entities'):
            self.parent().refresh_entities(self.get_type(), self.entity_combo)
    
    def set_airlines(self, airlines: list):
        """Устанавливает список авиакомпаний для выбора (для обратной совместимости)"""
        self.entity_combo.clear()
        for airline in airlines:
            self.entity_combo.addItem(airline)
    
    def set_entities(self, entities: list, entity_type: str):
        """Устанавливает список предприятий с ID"""
        self.entity_combo.clear()
        self.entity_combo.setEnabled(True)
        for entity_id, entity_name in entities:
            self.entity_combo.addItem(entity_name, entity_id)
    
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
        """Возвращает ID выбранного предприятия"""
        return self.entity_combo.currentData()
    
    def get_entity_name(self) -> str:
        """Возвращает название выбранного предприятия"""
        return self.entity_combo.currentText().strip()