# forms/widgets/multi_select_filter_button.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

# Раздел отделяется в названии показателя длинным тире с пробелами:
# «Внутренние регулярные — Пассажиры отправленные, чел.». Разделитель ставит
# разбор бланка 15-ГА (utils/ga15_airport_layout.py), а не пользователь.
GROUP_SEPARATOR = " — "


def split_group(label: str) -> Tuple[Optional[str], str]:
    """Делит подпись на раздел и собственное название. None — раздела нет.

    Иерархию можно было бы взять из `Indicator.parent_id`, как предлагал разбор,
    но в справочнике она не заполнена ни у одной записи: импортёр заводит
    показатели плоским списком. Раздел есть только там, где его проставил разбор
    бланка, — в самом названии.
    """
    head, separator, tail = label.partition(GROUP_SEPARATOR)
    if not separator or not head.strip() or not tail.strip():
        return None, label
    return head.strip(), tail.strip()


def group_items(items: List[Tuple[Any, str]]) -> List[Tuple[Optional[str], List[Tuple[Any, str]]]]:
    """Раскладывает список по разделам, сохраняя порядок их появления."""
    groups: List[Tuple[Optional[str], List[Tuple[Any, str]]]] = []
    index: Dict[Optional[str], int] = {}
    for value, label in items:
        group, leaf = split_group(label)
        if group not in index:
            index[group] = len(groups)
            groups.append((group, []))
        groups[index[group]][1].append((value, leaf))
    return groups


def worth_grouping(groups) -> bool:
    """Разделы показываются, только если их правда несколько.

    Кнопка общая: ею выбирают и авиакомпании, и виды маршрутов. Там раздел из
    названия не выделяется, и лишний уровень дерева только мешал бы.
    """
    return len({group for group, _ in groups if group is not None}) >= 2


class MultiSelectDialog(QDialog):
    """Выбор из списка с поиском и разделами.

    Прежде диалог строил по `QCheckBox` на каждую позицию в одном вертикальном
    списке — без поиска и группировки. Показателей в справочнике под сотню, и
    названия у них различаются хвостом: «Внутренние регулярные — Пассажиры
    отправленные, чел.» против «…Пассажиры принятые, чел.». Найти нужную строку
    прокруткой было нельзя, и фильтр по показателям не работал как фильтр
    (FUNC-10).
    """

    def __init__(self, title: str, items: List[Tuple[Any, str]],
                 checked: Set[Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(460, 520)

        self._leaves: List[Tuple[Any, QTreeWidgetItem]] = []
        self._groups: List[QTreeWidgetItem] = []
        self._total = len(items)

        layout = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.tree)
        self._build(items, checked)

        self.counter = QLabel()
        layout.addWidget(self.counter)

        row = QHBoxLayout()
        self.btn_all = QPushButton("Выбрать все")
        self.btn_none = QPushButton("Снять все")
        self.btn_all.clicked.connect(lambda: self.check_visible(True))
        self.btn_none.clicked.connect(lambda: self.check_visible(False))
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        layout.addLayout(row)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self._apply_search("")

    # --- построение --------------------------------------------------------

    def _build(self, items, checked: Set[Any]) -> None:
        groups = group_items(items)
        grouped = worth_grouping(groups)

        for group, leaves in groups:
            parent = None
            if grouped and group is not None:
                parent = QTreeWidgetItem(self.tree, [group])
                # Автотристейт: раздел сам отражает состояние своих строк, а щелчок
                # по разделу отмечает их все — то, ради чего разделы и заводились.
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                parent.setExpanded(True)
                self._groups.append(parent)

            for value, leaf_label in leaves:
                # Без разделов показываем подпись целиком: иначе у плоского списка
                # пропал бы кусок названия, отрезанный вместе с разделом.
                text = leaf_label if parent is not None else _full_label(group, leaf_label)
                item = QTreeWidgetItem(parent or self.tree, [text])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if value in checked else Qt.CheckState.Unchecked,
                )
                self._leaves.append((value, item))

    # --- поиск -------------------------------------------------------------

    def _apply_search(self, text: str) -> None:
        query = text.strip().casefold()

        for group in self._groups:
            group_matches = query and query in group.text(0).casefold()
            visible = 0
            for i in range(group.childCount()):
                child = group.child(i)
                shown = (not query) or group_matches or query in child.text(0).casefold()
                child.setHidden(not shown)
                visible += shown
            group.setHidden(visible == 0)
            if query:
                group.setExpanded(True)

        if not self._groups:
            for _, item in self._leaves:
                item.setHidden(bool(query) and query not in item.text(0).casefold())

        shown = len(self.visible_ids())
        self.counter.setText(
            f"Показано: {shown} из {self._total}" if query
            else f"Всего показателей: {self._total}"
        )

    # --- состояние ---------------------------------------------------------

    def visible_ids(self) -> List[Any]:
        return [value for value, item in self._leaves if not item.isHidden()]

    def checked_ids(self) -> Set[Any]:
        return {
            value for value, item in self._leaves
            if item.checkState(0) == Qt.CheckState.Checked
        }

    def check_visible(self, checked: bool) -> None:
        """Отмечает или снимает только показанные строки.

        Когда поиск не задан, показаны все, и кнопки работают как прежде. Когда
        задан — «Выбрать все» относится к найденному: отметить одним движением
        «Пассажиры отправленные» по всем разделам иначе нечем.

        Состояние ставится по строкам, а не по разделу: раздел разошёлся бы и на
        скрытые поиском строки.
        """
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for _, item in self._leaves:
            if not item.isHidden():
                item.setCheckState(0, state)


def _full_label(group: Optional[str], leaf: str) -> str:
    return f"{group}{GROUP_SEPARATOR}{leaf}" if group else leaf


class MultiSelectFilterButton(QPushButton):
    """
    Кнопка с диалогом выбора (как фильтры в маркетплейсах).
    Пустой выбор или «все отмечены» = не фильтровать по этому полю.
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

    def make_dialog(self) -> MultiSelectDialog:
        """Диалог с текущим списком и текущим выбором.

        Пустой выбор означает «все», поэтому в диалоге отмечено всё: снимать
        галочки пользователю понятнее, чем начинать с пустого списка.
        """
        all_ids = {v for v, _ in self._items}
        checked = self._selected if self._selected else all_ids
        return MultiSelectDialog(self._title, self._items, checked, self)

    def _open_dialog(self):
        dialog = self.make_dialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._selected = dialog.checked_ids()
        self._update_caption()
        self.selectionChanged.emit()
