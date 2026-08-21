# forms/widgets/reference_dialog.py
"""Окно ведения справочников (FUNC-1).

До его появления справочники нельзя было заполнить из приложения вообще: списки
выбора предприятий оставались пустыми, а импорт отвечал «предприятие не найдено».
Единственным способом завести аэропорт была правка базы в обход программы.

Вкладки строятся по описаниям из `ReferenceService`, а не пишутся по одной на
справочник: таблица, редактор и набор кнопок у всех четырёх одинаковы.
"""

from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from forms.widgets.dialog_buttons import set_caption
from services.reference_service import KINDS, Kind, ReferenceService, plural


class ReferenceEditor(QDialog):
    """Редактор одной записи. Поля берутся из описания справочника."""

    def __init__(self, kind: Kind, values: dict | None = None,
                 row_id: int | None = None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.row_id = row_id
        self.setWindowTitle(
            f"{kind.title}: {'изменение' if row_id else 'новая запись'}"
        )
        self.setMinimumWidth(420)
        self._editors: dict = {}
        self._build(values or {})

    def _build(self, values: dict) -> None:
        layout = QFormLayout(self)

        for field in self.kind.fields:
            if field.kind == "ref":
                combo = QComboBox()
                if field.allow_empty:
                    combo.addItem("— нет —", None)
                # Исключать текущую запись нужно только у ссылки на свой же справочник
                # (показатель не может быть себе родителем). Для ссылки на чужой
                # справочник тот же id — совсем другая запись, и вычёркивать её нельзя.
                exclude = self.row_id if field.ref == self.kind.key else None
                for ref_id, label in ReferenceService.choices(field.ref or "", exclude_id=exclude):
                    combo.addItem(label, ref_id)
                current = values.get(field.name)
                if current is not None:
                    index = combo.findData(current)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                self._editors[field.name] = combo
                layout.addRow(f"{field.label}:", combo)
            else:
                edit = QLineEdit(str(values.get(field.name) or ""))
                if field.max_length:
                    edit.setMaxLength(field.max_length)
                self._editors[field.name] = edit
                layout.addRow(f"{field.label}:", edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # Подписи задаются свои: перевода Qt в сборке нет, и стандартные кнопки
        # остаются английскими посреди русского окна.
        set_caption(buttons, QDialogButtonBox.StandardButton.Ok, "Сохранить")
        set_caption(buttons, QDialogButtonBox.StandardButton.Cancel, "Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self) -> dict:
        out = {}
        for field in self.kind.fields:
            editor = self._editors[field.name]
            if isinstance(editor, QComboBox):
                out[field.name] = editor.currentData()
            else:
                out[field.name] = editor.text()
        return out


class ReferenceTab(QWidget):
    """Один справочник: таблица и операции над выбранной строкой."""

    def __init__(self, kind_key: str, parent=None):
        super().__init__(parent)
        self.kind = ReferenceService.kind(kind_key)
        self._build()
        self.reload()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_row)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self.add_row)
        self.edit_btn = QPushButton("Изменить")
        self.edit_btn.clicked.connect(self.edit_row)
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.clicked.connect(self.delete_row)

        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.edit_btn)
        buttons.addWidget(self.delete_btn)

        if self.kind.has_active:
            self.active_btn: QPushButton | None = QPushButton("Вывести из работы")
            self.active_btn.clicked.connect(self.toggle_active)
            buttons.addWidget(self.active_btn)
        else:
            self.active_btn = None

        buttons.addStretch()
        layout.addLayout(buttons)

        self.hint = QLabel()
        self.hint.setStyleSheet("color: gray; font-size: 11px;")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    # --- данные ---

    def reload(self) -> None:
        self.rows = ReferenceService.list_rows(self.kind.key)

        headers = [column.label for column in self.kind.columns]
        if self.kind.has_active:
            headers.append("Действует")
        headers.append("Связано")

        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(self.rows))

        for r, row in enumerate(self.rows):
            c = 0
            for column in self.kind.columns:
                self.table.setItem(r, c, QTableWidgetItem(str(row.get(column.key, ""))))
                c += 1
            if self.kind.has_active:
                self.table.setItem(
                    r, c, QTableWidgetItem("да" if row["is_active"] else "нет")
                )
                c += 1
            self.table.setItem(r, c, QTableWidgetItem(str(row["usage"])))

        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            if self.kind.columns:
                header.setSectionResizeMode(
                    len(self.kind.columns) - 1, QHeaderView.ResizeMode.Stretch
                )
        self._update_buttons()

    def selected(self) -> dict | None:
        index = self.table.currentRow()
        if index < 0 or index >= len(self.rows):
            return None
        return self.rows[index]

    def _update_buttons(self) -> None:
        row = self.selected()
        self.edit_btn.setEnabled(row is not None)
        self.delete_btn.setEnabled(row is not None)
        if self.active_btn is not None:
            self.active_btn.setEnabled(row is not None)
            if row is not None:
                self.active_btn.setText(
                    "Вернуть в работу" if not row["is_active"] else "Вывести из работы"
                )

        if row is not None and row["usage"]:
            self.hint.setText(
                f"С выбранной записью связано {row['usage']} "
                f"{plural(row['usage'], self.kind.usage_forms)}. "
                + (
                    "Удалить её нельзя — выведите из работы, отчётность сохранится."
                    if self.kind.has_active
                    else "Удалить её нельзя."
                )
            )
        else:
            self.hint.setText("")

    # --- операции ---

    def add_row(self) -> None:
        editor = ReferenceEditor(self.kind, parent=self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply(ReferenceService.create(self.kind.key, editor.get_values()))

    def edit_row(self) -> None:
        row = self.selected()
        if row is None:
            return
        editor = ReferenceEditor(self.kind, values=self._edit_values(row),
                                 row_id=row["id"], parent=self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply(ReferenceService.update(self.kind.key, row["id"], editor.get_values()))

    def _edit_values(self, row: dict) -> dict:
        """Значения для редактора: ссылки нужны идентификаторами, а не подписями."""
        with_ids = ReferenceService.raw_values(self.kind.key, row["id"])
        return with_ids or {}

    def delete_row(self) -> None:
        row = self.selected()
        if row is None:
            return
        label = " / ".join(
            str(row.get(column.key, "")) for column in self.kind.columns
        ).strip(" /")
        confirm = QMessageBox.question(
            self,
            "Удаление записи",
            f"Удалить запись «{label}» из справочника «{self.kind.title}»?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._apply(ReferenceService.delete(self.kind.key, row["id"]))

    def toggle_active(self) -> None:
        row = self.selected()
        if row is None:
            return
        self._apply(
            ReferenceService.set_active(self.kind.key, row["id"], not row["is_active"])
        )

    def _apply(self, result: dict) -> None:
        if result.get("success"):
            self.reload()
            return
        QMessageBox.warning(
            self, "Справочник", result.get("message", "Не удалось выполнить операцию.")
        )


class ReferenceDialog(QDialog):
    """Окно со всеми справочниками."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Справочники")
        self.resize(760, 480)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.pages = {}
        for key, kind in KINDS.items():
            page = ReferenceTab(key, parent=self)
            self.pages[key] = page
            self.tabs.addTab(page, kind.title)
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        set_caption(buttons, QDialogButtonBox.StandardButton.Close, "Закрыть")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
