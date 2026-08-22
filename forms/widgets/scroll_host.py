# forms/widgets/scroll_host.py
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget


class HorizontalScrollHost(QScrollArea):
    """Панель, которую узкое окно прокручивает, а не ломает (BUG-32).

    Строка фильтров вкладки авиакомпаний требует по ширине больше, чем минимум
    главного окна: подписи, три кнопки выбора с жёстким `setMinimumWidth`,
    список вида таблицы и две кнопки. Явный минимум окна отменяет ограничение,
    которое компоновка выставила бы сама, поэтому окно спокойно ужимается до
    ширины, в которую строка не влезает. Места при этом `QHBoxLayout` берёт не у
    кнопок — их минимум задан явно и не сжимается, — а у подписей: «Показатель:»
    уезжает влево и печатается поверх соседней кнопки.

    Здесь содержимое получает свою ширину целиком, а окно — право быть уже:
    минимум по ширине снят, лишнее уходит в горизонтальную прокрутку.

    По высоте место под полосу прокрутки отведено всегда, а не только когда она
    видна. Считать высоту по текущему состоянию полосы соблазнительно, но при
    расширении окна полоса пропадает уже после того, как компоновка спросила
    размер, и отведённые под неё пиксели остаются висеть до следующего события.
    Постоянная полоска в полтора десятка пикселей предсказуемее скачущей высоты.

    Содержимое размерами области не растягивается (`setWidgetResizable(False)`):
    иначе в широком окне оно забирало бы и эту полоску, и панель фильтров то
    росла бы, то возвращалась к своей высоте.
    """

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # В описаниях типов PyQt6 полоса и область просмотра `Optional`, хотя
        # QScrollArea заводит их сама и `None` не отдаёт. Проверка здесь одна на
        # весь класс — дальше они берутся из полей.
        bar = self.horizontalScrollBar()
        viewport = self.viewport()
        if bar is None or viewport is None:
            raise RuntimeError("у области прокрутки нет полосы или области просмотра")
        self._bar = bar
        self._viewport = viewport

        # Обёртка не должна быть видна: фон и рамку рисует само содержимое.
        self._viewport.setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        self.setWidget(content)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fit_content()

    def _fit_content(self) -> None:
        """Содержимое: своя высота, ширина — своя или по области, что больше."""
        content = self.widget()
        if content is None:
            return
        hint = content.sizeHint()
        content.resize(max(hint.width(), self._viewport.width()), hint.height())

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._fit_content()

    def _height(self) -> int:
        content = self.widget()
        own = content.sizeHint().height() if content is not None else 0
        return own + self._bar.sizeHint().height()

    def sizeHint(self) -> QSize:
        content = self.widget()
        width = content.sizeHint().width() if content is not None else 0
        return QSize(width, self._height())

    def minimumSizeHint(self) -> QSize:
        # Ширина намеренно ничего не требует: в этом и смысл прокрутки.
        return QSize(0, self._height())
