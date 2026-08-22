"""Панель фильтров в узком окне: подписи не наезжают на кнопки (BUG-32).

Строке фильтров вкладки авиакомпаний нужно по ширине больше, чем минимум
главного окна. Явный `setMinimumSize(1200, 750)` отменяет ограничение, которое
компоновка выставила бы сама, и окно ужимается до ширины, в которую строка не
влезает. Кнопки при этом не сжимаются — их минимум задан явно, — поэтому место
`QHBoxLayout` отбирает у подписей: «Показатель:» уезжает влево и печатается
поверх соседней кнопки. В развёрнутом на весь экран окне этого не видно.

Проверяется следствие, а не устройство: при любой ширине окна прямоугольники
соседних виджетов строки не пересекаются. Отдельно проверено, что у проверки
есть зубы — без обёртки та же строка в той же ширине наезжает.

Виджеты создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.support import FilterWidgetCase

try:
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None

# Ширины меньше минимума окна (1200) — то, что пользователь получает, свернув
# окно из полноэкранного режима.
NARROW_WIDTHS = (1200, 1000, 900, 700)


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


def overlaps(row) -> list[tuple[str, str]]:
    """Пары соседних виджетов строки, чьи прямоугольники пересекаются."""
    found = []
    previous = None
    for i in range(row.count()):
        widget = row.itemAt(i).widget()
        if widget is None:
            continue
        box = widget.geometry()
        if previous is not None and box.x() <= previous[1]:
            found.append((previous[0], _name(widget)))
        previous = (_name(widget), box.right())
    return found


def _name(widget) -> str:
    text = getattr(widget, "text", None)
    return f"{type(widget).__name__}({text()})" if callable(text) else type(widget).__name__


@unittest.skipUnless(HAS_QT, "PyQt6 недоступен")
class FilterRowInNarrowWindowTest(FilterWidgetCase):
    """Панель фильтров в области прокрутки: ширину окна больше не требует."""

    def make_host(self):
        from forms.widgets.filter_widget import FilterWidget
        from forms.widgets.scroll_host import HorizontalScrollHost

        host = QWidget()
        self.addCleanup(host.deleteLater)
        layout = QVBoxLayout(host)
        panel = FilterWidget()
        area = HorizontalScrollHost(panel)
        layout.addWidget(area)
        layout.addStretch()
        host.show()
        return host, area, panel

    def test_labels_do_not_overlap_buttons_at_any_width(self):
        host, _area, panel = self.make_host()
        row = panel.layout().itemAt(0).layout()
        for width in NARROW_WIDTHS:
            with self.subTest(width=width):
                host.resize(width, 400)
                QApplication.processEvents()
                self.assertEqual([], overlaps(row))

    def test_check_has_teeth_without_the_scroll_area(self):
        """Без обёртки та же строка в той же ширине действительно наезжает.

        Иначе проверка выше осталась бы зелёной и после отката исправления —
        например, если бы окно просто перестало сужаться по другой причине.
        """
        from forms.widgets.filter_widget import FilterWidget

        panel = FilterWidget()
        self.addCleanup(panel.deleteLater)
        panel.show()
        row = panel.layout().itemAt(0).layout()
        row.setGeometry(QRect(12, 26, 900, 32))
        self.assertNotEqual([], overlaps(row))

    def test_window_may_be_narrower_than_the_panel(self):
        """Обёртка не требует ширины: минимум окна перестал зависеть от строки."""
        _host, area, panel = self.make_host()
        self.assertEqual(0, area.minimumSizeHint().width())
        self.assertGreater(panel.minimumSizeHint().width(), 1200)

    def test_panel_keeps_its_width_and_scrolls(self):
        """Содержимое не сжимается ниже своего минимума, лишнее уходит в прокрутку."""
        host, area, panel = self.make_host()
        needed = panel.minimumSizeHint().width()
        host.resize(900, 400)
        QApplication.processEvents()
        self.assertGreaterEqual(panel.width(), needed)
        self.assertTrue(area.horizontalScrollBar().isVisible())

    def test_panel_height_does_not_jump_with_the_scroll_bar(self):
        """Высота одна и та же при любой ширине: панель плюс полоска под полосу.

        Место под полосу отведено всегда. Высота по её текущему состоянию
        считалась бы с опозданием: при расширении окна полоса пропадает уже
        после того, как компоновка спросила размер, и отведённые пиксели
        оставались висеть. Сама панель при этом всегда своей высоты — область
        её не растягивает.
        """
        host, area, panel = self.make_host()
        expected = panel.sizeHint().height() + area.horizontalScrollBar().sizeHint().height()
        for width in (1400, 900, 1400, 700):
            with self.subTest(width=width):
                host.resize(width, 400)
                QApplication.processEvents()
                self.assertEqual(expected, area.height())
                self.assertEqual(panel.sizeHint().height(), panel.height())


if __name__ == "__main__":
    unittest.main()
