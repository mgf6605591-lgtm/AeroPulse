from typing import List, Tuple, Optional
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtGui import QPainter, QColor, QPalette


class MultiLevelHeaderView(QHeaderView):
    """
    Заголовок QTableView с двумя уровнями.
    Полностью отключены hover-эффекты для предотвращения артефактов.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._groups: List[Tuple[int, int, str]] = []
        self._group_height = 26
        
        # Отключаем все интерактивные эффекты
        self.setSectionsClickable(False)
        self.setHighlightSections(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        # Отключаем отслеживание мыши для hover
        self.setMouseTracking(False)
        
        # Убираем фокус с заголовка
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_groups(self, groups: List[Tuple[int, int, str]]):
        """groups = список кортежей (first_col, last_col_inclusive, label)."""
        self._groups = groups or []
        self.updateGeometries()
        self.viewport().update()

    def _find_group(self, col: int) -> Optional[Tuple[int, int, str]]:
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

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int):
        if not self._groups or rect.isEmpty():
            self._paint_standard_section(painter, rect, logicalIndex)
            return

        group = self._find_group(logicalIndex)
        if group is None:
            # Колонка вне группы — рисуем обычный заголовок на всю высоту
            self._paint_standard_section(painter, rect, logicalIndex)
            return

        first, last, label = group
        
        # Нижний заголовок (с названием колонки)
        lower_rect = QRect(
            rect.x(), rect.y() + self._group_height,
            rect.width(), rect.height() - self._group_height
        )
        
        # Рисуем нижнюю часть
        self._paint_section_no_hover(painter, lower_rect, logicalIndex)

        # Верхний заголовок группы — рисуем только для первой колонки группы
        if logicalIndex == first:
            # Вычисляем область группы
            start_pos = self.sectionViewportPosition(first)
            end_pos = self.sectionViewportPosition(last) + self.sectionSize(last)
            group_width = end_pos - start_pos
            
            if group_width > 0:
                group_rect = QRect(start_pos, rect.y(), group_width, self._group_height)
                
                # Проверяем видимость
                if group_rect.right() > 0 and group_rect.left() < self.width():
                    self._paint_group_header(painter, group_rect, label)

    def _paint_standard_section(self, painter: QPainter, rect: QRect, logicalIndex: int):
        """Отрисовка стандартной секции без hover."""
        # Получаем цвета из палитры
        palette = self.palette()
        bg_color = palette.color(QPalette.ColorRole.Button)
        border_color = palette.color(QPalette.ColorRole.Mid)
        text_color = palette.color(QPalette.ColorRole.ButtonText)
        
        # Рисуем фон
        painter.fillRect(rect, bg_color)
        
        # Рисуем границу
        painter.setPen(border_color)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        
        # Рисуем текст
        text = self.model().headerData(logicalIndex, Qt.Orientation.Horizontal, 
                                      Qt.ItemDataRole.DisplayRole)
        if text:
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text))

    def _paint_section_no_hover(self, painter: QPainter, rect: QRect, logicalIndex: int):
        """Отрисовка секции без hover (для нижней части)."""
        palette = self.palette()
        bg_color = palette.color(QPalette.ColorRole.Button)
        border_color = palette.color(QPalette.ColorRole.Mid)
        text_color = palette.color(QPalette.ColorRole.ButtonText)
        
        # Рисуем фон
        painter.fillRect(rect, bg_color)
        
        # Рисуем границу
        painter.setPen(border_color)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        
        # Рисуем текст
        text = self.model().headerData(logicalIndex, Qt.Orientation.Horizontal,
                                      Qt.ItemDataRole.DisplayRole)
        if text:
            painter.setPen(text_color)
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

    def get_groups(self) -> List[Tuple[int, int, str]]:
        """Копия групп заголовка (first_col, last_col, подпись) для экспорта в XLSX."""
        return list(self._groups)