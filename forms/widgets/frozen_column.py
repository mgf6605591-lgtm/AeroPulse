# forms/widgets/frozen_column.py
"""Закреплённая первая колонка сводной таблицы.

В своде колонок столько, что «Показатель» уезжает за левый край первым же
движением полосы прокрутки: дальше видны одни числа, а к какой строке бланка они
относятся — нет. Свод по маршрутам на трёх а/к за три месяца — это сорок пять
колонок, то есть случай не редкий, а обычный.

Закрепления колонок в `QTableView` нет, поэтому первая колонка показывается ещё
раз — второй таблицей поверх той же модели, шириной ровно в эту колонку. Она не
прокручивается вбок, и настоящая первая колонка уезжает под неё. Так устроен и
пример «Frozen Column» в самом Qt.

Обе таблицы делят модель и модель выделения: выделенная строка подсвечивается в
обеих, а прокрутка по вертикали синхронна. Заголовок у накладки свой, но того же
класса и с теми же группами — иначе шапка над закреплённой колонкой оказалась бы
другой высоты, и строки разъехались бы по вертикали.
"""
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractItemView, QTableView

from forms.widgets.multilevel_header import MultiLevelHeaderView


def _part[T](part: T | None, name: str) -> T:
    """Часть таблицы, которую Qt заводит сама: заголовок, полоса, область.

    В описаниях типов PyQt6 все они `Optional`, хотя `QTableView` создаёт их в
    своём конструкторе и `None` не отдаёт ни разу. Проверять это на каждом вызове
    значило бы прятать настоящую поломку за молчаливым `if`; здесь она хотя бы
    назовёт себя.
    """
    if part is None:
        raise RuntimeError(f"у таблицы нет {name} — такого QTableView не бывает")
    return part


class FrozenFirstColumn(QObject):
    """Копия первой колонки поверх таблицы: при прокрутке вбок она остаётся."""

    def __init__(self, table: QTableView):
        super().__init__(table)
        self._table = table
        self._enabled = False

        self._table_header = _part(table.horizontalHeader(), "заголовка")
        self._table_rows = _part(table.verticalHeader(), "номеров строк")
        self._table_vbar = _part(table.verticalScrollBar(), "полосы прокрутки")
        self._table_hbar = _part(table.horizontalScrollBar(), "полосы прокрутки")
        self._table_viewport = _part(table.viewport(), "области просмотра")

        self._view = QTableView(table)
        self._header = MultiLevelHeaderView(self._view)
        self._view.setHorizontalHeader(self._header)
        self._header.setStretchLastSection(False)
        self._view_vbar = _part(self._view.verticalScrollBar(), "полосы прокрутки")

        # Накладка — не самостоятельная таблица: ни фокуса, ни своих полос
        # прокрутки, ни номеров строк (они остаются у настоящей таблицы слева).
        self._view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _part(self._view.verticalHeader(), "номеров строк").hide()
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setFrameShape(QTableView.Shape.NoFrame)
        self._view.setSelectionBehavior(table.selectionBehavior())
        self._view.setSelectionMode(table.selectionMode())
        self._view.setAlternatingRowColors(table.alternatingRowColors())
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Прокрутка по пикселям с обеих сторон: при прокрутке по ячейкам
        # половина строки у нижнего края накладки и таблицы отрезалась бы
        # по-разному, и строки разъезжались бы на глаз.
        for view in (table, self._view):
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self._table_viewport.stackUnder(self._view)

        self._connect()
        table.installEventFilter(self)
        self._view.hide()

    # --- подписки -----------------------------------------------------------

    def _connect(self) -> None:
        self._table_header.sectionResized.connect(self._on_table_column_resized)
        # Шапка настоящей таблицы растёт, когда длинная подпись переносится на
        # несколько строк, — накладка обязана вырасти вместе с ней, иначе строки
        # под двумя шапками разной высоты разъедутся.
        self._table_header.geometriesChanged.connect(self._update_geometry)
        self._table_rows.sectionResized.connect(self._on_row_resized)
        self._header.sectionResized.connect(self._on_frozen_column_resized)

        self._table_vbar.valueChanged.connect(self._view_vbar.setValue)
        # И обратно: колесо мыши над накладкой прокручивает её собственную
        # полосу, скрытую, но живую, — без этой связи таблица под ней стояла бы.
        self._view_vbar.valueChanged.connect(self._table_vbar.setValue)

    def eventFilter(self, obj, event) -> bool:
        if event is not None and event.type() == QEvent.Type.Resize:
            self._update_geometry()
        return False

    def _on_table_column_resized(self, index: int, _old: int, size: int) -> None:
        if index == 0:
            self._view.setColumnWidth(0, size)
            self._update_geometry()

    def _on_frozen_column_resized(self, index: int, _old: int, size: int) -> None:
        """Границу закреплённой колонки тянут за её же заголовок — он сверху."""
        if index == 0:
            self._table.setColumnWidth(0, size)

    def _on_row_resized(self, index: int, _old: int, size: int) -> None:
        self._view.setRowHeight(index, size)

    # --- состояние ----------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """Закреплять ли колонку. В подробной таблице первая колонка — «ID»."""
        self._enabled = enabled
        if enabled:
            self.sync()
        else:
            self._view.hide()
            self._report_cover()

    def set_groups(self, groups: list[tuple[int, int, str]]) -> None:
        """Те же группы, что и у таблицы: от них зависит высота шапки.

        Первая колонка ни в одну группу не входит, и её заголовок рисуется на всю
        высоту, — но пустая полоса групп над ней обязана быть, иначе шапка
        накладки ниже, а строки под ней смещены.
        """
        self._header.set_groups(groups)
        if self._enabled:
            self._update_geometry()

    def sync(self) -> None:
        """Подхватывает модель, выделение и ширины после загрузки данных."""
        if not self._enabled:
            return

        model = self._table.model()
        if model is None or model.columnCount() == 0:
            self._view.hide()
            return

        if self._view.model() is not model:
            self._view.setModel(model)
        # Модель выделения таблица заводит заново при каждой смене модели, и
        # прежняя вместе с ней выбрасывается: связывать их нужно после, а не раз
        # и навсегда в конструкторе.
        selection = self._table.selectionModel()
        if selection is not None and self._view.selectionModel() is not selection:
            self._view.setSelectionModel(selection)

        for col in range(1, model.columnCount()):
            self._view.setColumnHidden(col, True)
        self._view.setColumnHidden(0, False)
        self._view.setColumnWidth(0, self._table.columnWidth(0))

        self._update_geometry()
        self._view.show()

    def keep_current_visible(self, column: int) -> None:
        """Отодвигает прокрутку, если текущая ячейка ушла под закреплённую.

        Стрелкой влево из середины свода можно довести курсор до второй колонки,
        и таблица считает её показанной — она и правда в области просмотра, но
        накрыта накладкой. В самом Qt тот же случай разбирается переопределением
        `moveCursor`; здесь достаточно поправить прокрутку постфактум.
        """
        if not self._enabled or column <= 0:
            return
        frozen_width = self._table.columnWidth(0)
        position = self._table.columnViewportPosition(column)
        if 0 <= position < frozen_width:
            self._table_hbar.setValue(
                self._table_hbar.value() - (frozen_width - position)
            )

    def _report_cover(self) -> None:
        """Заголовок таблицы должен знать, что его левый край перекрыт.

        Иначе подпись месяца центрируется по всей области просмотра, часть
        которой закрыта накладкой, и уезжает под неё обрезанной.
        """
        if isinstance(self._table_header, MultiLevelHeaderView):
            width = self._table.columnWidth(0) if self._enabled else 0
            self._table_header.set_left_cover(width)

    def _match_header_height(self) -> None:
        """Шапка накладки — той же высоты, что и шапка таблицы.

        Сама она мерит одну колонку и вышла бы ниже: перенос длинных подписей
        поднимает высоту по самой высокой колонке свода, а их накладка не видит.
        Берётся вычисленная высота, а не текущая: на этот момент таблица ещё не
        успела применить новую.
        """
        if isinstance(self._table_header, MultiLevelHeaderView):
            self._header.set_height_floor(self._table_header.required_height())

    def _update_geometry(self) -> None:
        # Заголовок сообщает о смене геометрии и в тот момент, когда таблицу уже
        # сносят: обращение к ней оттуда падает на удалённом объекте.
        if sip.isdeleted(self._table):
            return
        self._report_cover()
        self._match_header_height()
        frame = self._table.frameWidth()
        # `isHidden`, а не `isVisible`: пока окно не показано, видимым не
        # считается ни один дочерний виджет, и номера строк съели бы отступ.
        left = frame + (0 if self._table_rows.isHidden() else self._table_rows.width())
        self._view.setGeometry(
            left, frame,
            self._table.columnWidth(0),
            self._table_viewport.height() + self._table_header.height(),
        )

    # --- для проверок -------------------------------------------------------

    @property
    def view(self) -> QTableView:
        """Сама накладка — чтобы тест мог посмотреть, что она показывает."""
        return self._view

    def is_enabled(self) -> bool:
        return self._enabled
