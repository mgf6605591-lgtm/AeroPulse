# forms/widgets/multi_select_filter_button.py
from __future__ import annotations

from typing import Any, List, Optional, Set, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class MultiSelectFilterButton(QPushButton):
    """
    Кнопка с диалогом чекбоксов (как фильтры в маркетплейсах).
    Пустой выбор или «все отмечены» = не фильтровать по этому полю.
    QCheckBox: клик по тексту переключает состояние.
    """

    selectionChanged = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._items: List[Tuple[Any, str]] = []
        self._selected: Set[Any] = set()
        self.clicked.connect(self._open_dialog)
        self._update_caption()

    def set_items(self, items: List[Tuple[Any, str]]):
        """Список (id, подпись). id должен быть hashable; дубликаты id отбрасываются."""
        seen: Set[Any] = set()
        out: List[Tuple[Any, str]] = []
        for v, lbl in items:
            if v is None or v in seen:
                continue
            seen.add(v)
            out.append((v, str(lbl)))
        self._items = out
        valid = {v for v, _ in self._items}
        self._selected = self._selected & valid
        self._update_caption()

    def clear_selection(self):
        self._selected = set()
        self._update_caption()

    def filter_active_ids(self) -> Optional[List[Any]]:
        """
        None — не ограничивать (все).
        Список id — только выбранные (подмножество справочника).
        """
        if not self._items:
            return None
        all_ids = {v for v, _ in self._items}
        if not self._selected or self._selected == all_ids:
            return None
        return sorted(self._selected, key=lambda x: (str(type(x).__name__), str(x)))

    def _update_caption(self):
        n_items = len(self._items)
        if n_items == 0:
            self.setText(f"{self._title}: —")
            return
        all_ids = {v for v, _ in self._items}
        if not self._selected or self._selected == all_ids:
            self.setText(f"{self._title}: все ({n_items})")
        else:
            self.setText(f"{self._title}: выбрано {len(self._selected)}")

    def _open_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(self._title)
        dlg.setMinimumWidth(380)
        dlg.setMinimumHeight(420)
        layout = QVBoxLayout(dlg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(6, 6, 6, 6)

        all_ids = {v for v, _ in self._items}
        effective = self._selected if self._selected else all_ids
        checks: List[Tuple[Any, QCheckBox]] = []
        for vid, lbl in self._items:
            cb = QCheckBox(lbl)
            cb.setChecked(vid in effective)
            checks.append((vid, cb))
            inner_layout.addWidget(cb)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        row = QHBoxLayout()
        btn_all = QPushButton("Выбрать все")
        btn_none = QPushButton("Снять все")
        row.addWidget(btn_all)
        row.addWidget(btn_none)
        layout.addLayout(row)

        def do_all():
            for _, cb in checks:
                cb.setChecked(True)

        def do_none():
            for _, cb in checks:
                cb.setChecked(False)

        btn_all.clicked.connect(do_all)
        btn_none.clicked.connect(do_none)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        layout.addWidget(box)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_sel: Set[Any] = set()
        for vid, cb in checks:
            if cb.isChecked():
                new_sel.add(vid)
        self._selected = new_sel
        self._update_caption()
        self.selectionChanged.emit()
