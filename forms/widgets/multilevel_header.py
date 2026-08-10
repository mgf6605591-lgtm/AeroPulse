# forms/widgets/multilevel_header.py
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtGui import QPainter, QPalette


class MultiLevelHeaderView(QHeaderView):
    """
    Заголовок QTableView с двумя уровнями.
    Секции рисуются целиком своими средствами, поэтому hover на вид не влияет.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._groups: list[tuple[int, int, str]] = []
        self._group_height = 26

        # Секция не подсвечивается и не нажимается: `paintSection` ни разу не
        # обращается к базовой отрисовке, состояние секции в неё не входит.
        self.setSectionsClickable(False)
        self.setHighlightSections(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # Убираем фокус с заголовка
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)

        # `WA_TransparentForMouseEvents` заводился против hover-артефактов, но
        # отдавал мимо заголовка **все** события мыши — вместе с ними пропала и
        # возможность тянуть границы колонок (BUG-10). Артефактам взяться неоткуда
        # и без него: заголовок рисует себя сам и состояние секции не читает.
        # Отслеживание мыши нужно, чтобы у границы колонки появлялся курсор
        # изменения ширины, — иначе тянуть можно, но не догадаешься.
        self.setMouseTracking(True)

    def set_groups(self, groups: list[tuple[int, int, str]]):
        """groups = список кортежей (first_col, last_col_inclusive, label)."""
        self._groups = groups or []
        self.updateGeometries()
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def _find_group(self, col: int) -> tuple[int, int, str] | None:
        for g in self._groups:
            if g[0] <= col <= g[1]:
                return g
        return None

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        if self._groups:
            return QSize(s.width(), s.height() + self._group_height)
        return s

    def sectionSizeFromContents(self, logicalIndex: int) -> QSize:
        s = super().sectionSizeFromContents(logicalIndex)
        if self._groups:
            return QSize(s.width(), s.height() + self._group_height)
        return s

    def paintSection(self, painter: QPainter | None, rect: QRect, logicalIndex: int):
        if painter is None:
            return
        if not self._groups or rect.isEmpty():
            self._paint_section(painter, rect, logicalIndex)
            return

        group = self._find_group(logicalIndex)
        if group is None:
            # Колонка вне группы — рисуем обычный заголовок на всю высоту
            self._paint_section(painter, rect, logicalIndex)
            return

        first, last, label = group
        
        # Нижний заголовок (с названием колонки)
        lower_rect = QRect(
            rect.x(), rect.y() + self._group_height,
            rect.width(), rect.height() - self._group_height
        )
        
        # Рисуем нижнюю часть
        self._paint_section(painter, lower_rect, logicalIndex)

        # Подпись группы рисуется при отрисовке **любой** её видимой колонки, а
        # прямоугольник ограничивается видимой областью. Условием была первая
        # колонка группы (`logicalIndex == first`), а Qt вызывает paintSection
        # только для видимых секций: стоило прокрутить таблицу вправо настолько,
        # что первая колонка группы ушла за левый край, и подпись месяца
        # пропадала целиком — при том что колонки группы на экране (BUG-20).
        # Случай не краевой, а обычный: свод по маршрутам строит по пять колонок
        # на авиакомпанию в каждом месяце, и на трёх а/к за три месяца сорок пять
        # колонок на экран не помещаются физически.
        group_rect = self._visible_group_rect(first, last, rect.y())
        if group_rect is not None:
            self._paint_group_header(painter, group_rect, label)

    def _visible_group_rect(self, first: int, last: int, top: int) -> QRect | None:
        """Видимая часть полосы группы, или None, если группа целиком за краем.

        Подпись центрируется по видимой части, поэтому у наполовину прокрученной
        группы она остаётся на виду, а не уезжает за край вместе с её началом.
        """
        start_pos = self.sectionViewportPosition(first)
        end_pos = self.sectionViewportPosition(last) + self.sectionSize(last)
        if end_pos <= start_pos:
            return None

        group_rect = QRect(start_pos, top, end_pos - start_pos, self._group_height)
        viewport = self.viewport()
        visible = group_rect.intersected(
            QRect(0, top, viewport.width() if viewport else 0, self._group_height)
        )
        return visible if not visible.isEmpty() else None

    def _paint_section(self, painter: QPainter, rect: QRect, logicalIndex: int):
        """Отрисовка секции заголовка: фон, рамка, подпись колонки.

        Метод был один, а копий — две: `_paint_standard_section` для колонки без
        группы и `_paint_section_no_hover` для нижней половины сгруппированной.
        Отличались они только именем и комментарием (ARCH-8), а разница между
        случаями — в прямоугольнике, который передаёт вызывающий.
        """
        palette = self.palette()
        painter.fillRect(rect, palette.color(QPalette.ColorRole.Button))

        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        model = self.model()
        text = model.headerData(logicalIndex, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.DisplayRole) if model else None
        if text:
            painter.setPen(palette.color(QPalette.ColorRole.ButtonText))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text))

    def _paint_group_header(self, painter: QPainter, rect: QRect, label: str):
        """Отрисовка заголовка группы."""
        palette = self.palette()
        bg_color = palette.color(QPalette.ColorRole.Button).darker(105)
        border_color = palette.color(QPalette.ColorRole.Mid)
        text_color = palette.color(QPalette.ColorRole.ButtonText)
        
        # Рисуем фон группы
        painter.fillRect(rect.adjusted(0, 0, -1, -1), bg_color)
        
        # Рисуем границу
        painter.setPen(border_color)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        
        # Рисуем текст (жирный шрифт)
        painter.setPen(text_color)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def get_groups(self) -> list[tuple[int, int, str]]:
        """Копия групп заголовка (first_col, last_col, подпись) для экспорта в XLSX."""
        return list(self._groups)