# forms/widgets/multilevel_header.py
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView
from PyQt6.QtCore import QEvent, Qt, QMetaObject, QRect, QSize
from PyQt6.QtGui import QFontMetrics, QPainter, QPalette


# Отступ подписи от боковых границ секции: вплотную к линии текст читается хуже,
# и на эти пиксели уменьшается место, по которому подпись переносится.
TEXT_MARGIN = 4
# Запас по высоте, чтобы строки подписи не упирались в границы секции.
TEXT_PADDING = 6


def wrap_header_text(text: str, width: int, metrics) -> list[str]:
    """Разбивает подпись на строки, каждая из которых влезает в `width` пикселей.

    Заголовок обрезался по ширине колонки, и от названия предприятия оставалась
    середина: «рное общество "Авиакомпания "». Перенос показывает название
    целиком при любой ширине — ценой высоты шапки, которая под него растёт.

    Слово, которое не помещается целиком (узкая колонка, длинное название),
    разрывается по буквам: иначе «при любой ширине» не выполняется — такое слово
    осталось бы обрезанным.

    `metrics` — что угодно с методом `horizontalAdvance(str)`, обычно QFontMetrics.
    """
    text = str(text)
    if width <= 0:
        return [text]

    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        current = ""
        for word in words:
            probe = f"{current} {word}" if current else word
            if metrics.horizontalAdvance(probe) <= width:
                current = probe
                continue
            if current:
                lines.append(current)
            *head, current = _split_word(word, width, metrics)
            lines.extend(head)
        lines.append(current)
    return lines


def _split_word(word: str, width: int, metrics) -> list[str]:
    """Слово по кускам в ширину колонки; последний кусок — начало новой строки."""
    parts: list[str] = []
    current = ""
    for char in word:
        probe = current + char
        if current and metrics.horizontalAdvance(probe) > width:
            parts.append(current)
            current = char
        else:
            current = probe
    return parts + [current]


class MultiLevelHeaderView(QHeaderView):
    """
    Заголовок QTableView с двумя уровнями.
    Секции рисуются целиком своими средствами, поэтому hover на вид не влияет.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._groups: list[tuple[int, int, str]] = []
        self._group_height = 26
        # Сколько пикселей слева перекрыто закреплённой колонкой. Подпись группы
        # центрируется по видимой части, а «видимая» — это не «в области
        # просмотра»: под накладкой её не видно (см. forms/widgets/frozen_column.py).
        self._left_cover = 0
        # Высота, ниже которой шапка не опускается: накладке закреплённой колонки
        # её задаёт настоящая таблица, иначе шапки будут разной высоты и строки
        # под ними разъедутся (см. forms/widgets/frozen_column.py).
        self._height_floor = 0
        # Сколько строк занимает подпись при такой ширине. Высота шапки
        # пересчитывается на каждый запрос размера — а это перенос всех подписей
        # свода, где колонок бывает под сотню.
        self._line_cache: dict[tuple[str, int], int] = {}
        # Пересчёт высоты меняет геометрию секций, а та зовёт пересчёт: флаг
        # разрывает круг.
        self._updating_geometries = False

        # Ширину тянут мышью, и от неё зависит, во сколько строк ляжет подпись:
        # шапка обязана перемериться, иначе перенесённый текст окажется за её
        # нижней границей.
        self.sectionResized.connect(self._on_section_resized)

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
        self._refresh_geometries()

    def set_left_cover(self, width: int):
        """Ширина накладки закреплённой колонки поверх левого края заголовка."""
        width = max(0, int(width))
        if width == self._left_cover:
            return
        self._left_cover = width
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def _find_group(self, col: int) -> tuple[int, int, str] | None:
        for g in self._groups:
            if g[0] <= col <= g[1]:
                return g
        return None

    def setModel(self, model):
        """Новая модель — новые подписи, а значит и другая высота шапки.

        Смену данных заголовок иначе не заметит: ширины остались прежними,
        `sectionResized` не приходит, — и свод с длинными названиями предприятий
        встал бы под шапку, померенную по коротким.
        """
        previous = self.model()
        if previous is not None:
            try:
                previous.modelReset.disconnect(self._on_header_contents_changed)
                previous.headerDataChanged.disconnect(self._on_header_contents_changed)
            except TypeError:  # подписки не было — модель ставили не мы
                pass

        super().setModel(model)
        self._line_cache.clear()
        if model is not None:
            model.modelReset.connect(self._on_header_contents_changed)
            model.headerDataChanged.connect(self._on_header_contents_changed)

    def _on_header_contents_changed(self, *_args) -> None:
        self._refresh_geometries()

    def set_height_floor(self, height: int) -> None:
        """Не быть ниже этой высоты — для накладки закреплённой колонки."""
        height = max(0, int(height))
        if height == self._height_floor:
            return
        self._height_floor = height
        self._refresh_geometries()

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        height = s.height() + (self._group_height if self._groups else 0)
        return QSize(s.width(), max(height, self.required_height()))

    def required_height(self) -> int:
        """Высота, при которой видна каждая подпись целиком, со всеми переносами."""
        metrics = self.fontMetrics()
        text_height = metrics.height()

        model = self.model()
        if model is not None:
            for col in range(model.columnCount()):
                if self.isSectionHidden(col):
                    continue
                lines = self._line_count(col, self.sectionSize(col), metrics)
                text_height = max(text_height, lines * metrics.height())

        height = text_height + TEXT_PADDING
        if self._groups:
            height += self._group_height
        return max(height, self._height_floor)

    def _line_count(self, logicalIndex: int, width: int, metrics: QFontMetrics) -> int:
        text = self._section_text(logicalIndex)
        if not text:
            return 1
        key = (text, max(0, width - 2 * TEXT_MARGIN))
        cached = self._line_cache.get(key)
        if cached is None:
            cached = len(wrap_header_text(text, key[1], metrics))
            # Ключей столько, сколько пар «подпись — ширина»; за долгую сессию с
            # разными сводами их набирается неограниченно много.
            if len(self._line_cache) > 4096:
                self._line_cache.clear()
            self._line_cache[key] = cached
        return cached

    def _section_text(self, logicalIndex: int) -> str:
        model = self.model()
        if model is None:
            return ""
        text = model.headerData(logicalIndex, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.DisplayRole)
        return "" if text is None else str(text)

    def _on_section_resized(self, *_args) -> None:
        self._refresh_geometries()

    def changeEvent(self, event):
        """Сменился шрифт — прежние переносы посчитаны не по нему."""
        if event is not None and event.type() == QEvent.Type.FontChange:
            self._line_cache.clear()
            self._refresh_geometries()
        super().changeEvent(event)

    def _refresh_geometries(self) -> None:
        """Перемерить шапку: подписи или ширины изменились."""
        if self._updating_geometries:
            return
        self._updating_geometries = True
        try:
            self.updateGeometries()

            # Свою высоту заголовок не выбирает: её ставит таблица, и спрашивает
            # `sizeHint` она только когда перестраивает себя сама — от смены
            # ширины колонки, но не от смены подписей. Без этого толчка перенос
            # был бы посчитан, а места под него не появилось бы.
            # `updateGeometries` у QAbstractItemView — слот, поэтому зовётся по
            # имени, минуя `protected`.
            view = self.parentWidget()
            if isinstance(view, QAbstractItemView):
                QMetaObject.invokeMethod(view, "updateGeometries")
        finally:
            self._updating_geometries = False

        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

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
        width = viewport.width() if viewport else 0
        visible = group_rect.intersected(
            QRect(self._left_cover, top, max(0, width - self._left_cover), self._group_height)
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

        text = self._section_text(logicalIndex)
        if text:
            painter.setPen(palette.color(QPalette.ColorRole.ButtonText))
            self._draw_wrapped(painter, rect, text)

    def _draw_wrapped(self, painter: QPainter, rect: QRect, text: str):
        """Подпись в несколько строк по центру секции.

        Раньше здесь был `drawText` с `AlignCenter`: одна строка, а всё, что не
        влезло в ширину колонки, просто обрезалось по её границам.
        """
        metrics = painter.fontMetrics()
        inner = rect.adjusted(TEXT_MARGIN, 0, -TEXT_MARGIN, 0)
        lines = wrap_header_text(text, inner.width(), metrics)
        line_height = metrics.height()

        top = inner.y() + max(0, (inner.height() - line_height * len(lines)) // 2)
        for offset, line in enumerate(lines):
            painter.drawText(
                QRect(inner.x(), top + offset * line_height, inner.width(), line_height),
                Qt.AlignmentFlag.AlignCenter, line,
            )

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
        
        # Рисуем текст (жирный шрифт). Шрифт возвращается обратно: painter один
        # на всю отрисовку, и жирное начертание досталось бы подписям колонок,
        # которые рисуются следующими, — а меряются они обычным шрифтом.
        painter.save()
        painter.setPen(text_color)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        # Подпись группы — в одну строку: полоса групп фиксированной высоты, и
        # перенос вылез бы поверх названий колонок. Места ей хватает: группа —
        # это месяц над несколькими колонками, а не одна узкая колонка.
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def get_groups(self) -> list[tuple[int, int, str]]:
        """Копия групп заголовка (first_col, last_col, подпись) для экспорта в XLSX."""
        return list(self._groups)