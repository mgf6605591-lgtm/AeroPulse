"""Клавиша Delete в таблицах данных (BUG-21, BUG-22).

Главное окно создаёт два `DataTableWidget` — вкладки авиакомпаний и аэропортов, —
поэтому шорткат с контекстом по умолчанию (`WindowShortcut`) регистрируется в окне
дважды. Qt считает такую пару неоднозначной и не вызывает ни один обработчик
(BUG-21), а пока шорткат всё же срабатывает, он срабатывает при фокусе на любом
виджете окна, включая поля фильтров (BUG-22).

Проверяется поведение, а не только свойство: окно собирается как настоящее — поле
фильтра и две таблицы, — а клавиша доставляется через `QTest`, то есть проходит
через карту шорткатов Qt так же, как нажатие пользователя. Обработчик подменён
счётчиком: сами записи не удаляются, база не нужна.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QVBoxLayout, QWidget
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


if HAS_QT:
    from forms.widgets.data_table_widget import DataTableWidget

    class SpyTableWidget(DataTableWidget):
        """Считает срабатывания шортката вместо удаления записей.

        Подмена возможна потому, что `QShortcut` соединяется с `self._on_delete_clicked`
        в конструкторе: у наследника это уже переопределённый метод.
        """

        deletes = 0

        def _on_delete_clicked(self):
            self.deletes += 1


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DeleteShortcutTest(unittest.TestCase):
    """Два виджета таблиц и поле фильтра в одном окне — как в главном окне."""

    def setUp(self):
        self.window = QWidget()
        self.addCleanup(self.window.deleteLater)
        layout = QVBoxLayout(self.window)

        self.filter_field = QLineEdit()
        layout.addWidget(self.filter_field)

        self.airlines = SpyTableWidget()
        self.airports = SpyTableWidget()
        layout.addWidget(self.airlines)
        layout.addWidget(self.airports)

        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.window.activateWindow()
        QApplication.setActiveWindow(self.window)

    def press_delete(self, widget):
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        self.assertTrue(widget.hasFocus(), "фокус не установлен — проверка бессмысленна")
        QTest.keyClick(widget, Qt.Key.Key_Delete)

    def test_delete_reaches_the_focused_table(self):
        """BUG-21: при неоднозначном шорткате не срабатывает ни один обработчик."""
        self.press_delete(self.airlines.get_table_view())

        self.assertEqual(1, self.airlines.deletes)

    def test_delete_does_not_reach_the_other_table(self):
        self.press_delete(self.airlines.get_table_view())

        self.assertEqual(0, self.airports.deletes)

    def test_each_table_answers_for_itself(self):
        self.press_delete(self.airports.get_table_view())

        self.assertEqual(0, self.airlines.deletes)
        self.assertEqual(1, self.airports.deletes)

    def test_delete_in_filter_field_deletes_nothing(self):
        """BUG-22: Delete в поле фильтра стирает символ, а не записи."""
        self.filter_field.setText("Якутия")
        self.filter_field.setCursorPosition(0)

        self.press_delete(self.filter_field)

        self.assertEqual(0, self.airlines.deletes)
        self.assertEqual(0, self.airports.deletes)
        self.assertEqual("кутия", self.filter_field.text())

    def test_shortcut_is_scoped_to_its_widget(self):
        for widget in (self.airlines, self.airports):
            self.assertEqual(
                Qt.ShortcutContext.WidgetWithChildrenShortcut,
                widget.delete_shortcut.context(),
            )


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SingleTableDeleteShortcutTest(unittest.TestCase):
    """Окно с одной таблицей: BUG-22 отдельно от BUG-21.

    Пока в окне два одинаковых шортката, Delete не доходит никуда — в том числе
    до фильтров, но по чужой причине. С одной таблицей неоднозначности нет, и
    виден собственно контекст: с `WindowShortcut` нажатие на фильтре открывало бы
    диалог удаления выделенных записей.

    Опасны здесь именно комбобоксы — период и выбор предприятия набраны ими
    (`forms/widgets/filter_widget.py`, `forms/widgets/airport_filter_widget.py`).
    Текстовое поле Qt защищает сама: `QLineEdit` перехватывает ShortcutOverride
    для клавиш правки, поэтому Delete в нём стирает символ при любом контексте.
    """

    def setUp(self):
        self.window = QWidget()
        self.addCleanup(self.window.deleteLater)
        layout = QVBoxLayout(self.window)

        self.month_combo = QComboBox()
        self.month_combo.addItems(["Январь", "Февраль"])
        layout.addWidget(self.month_combo)

        self.filter_field = QLineEdit()
        layout.addWidget(self.filter_field)

        self.table = SpyTableWidget()
        layout.addWidget(self.table)

        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.window.activateWindow()
        QApplication.setActiveWindow(self.window)

    def test_delete_on_a_filter_combo_deletes_nothing(self):
        self.month_combo.setFocus(Qt.FocusReason.OtherFocusReason)

        QTest.keyClick(self.month_combo, Qt.Key.Key_Delete)

        self.assertEqual(0, self.table.deletes)

    def test_delete_in_filter_field_erases_a_character(self):
        self.filter_field.setText("Якутия")
        self.filter_field.setCursorPosition(0)
        self.filter_field.setFocus(Qt.FocusReason.OtherFocusReason)

        QTest.keyClick(self.filter_field, Qt.Key.Key_Delete)

        self.assertEqual(0, self.table.deletes)
        self.assertEqual("кутия", self.filter_field.text())

    def test_delete_in_the_table_still_works(self):
        table = self.table.get_table_view()
        table.setFocus(Qt.FocusReason.OtherFocusReason)

        QTest.keyClick(table, Qt.Key.Key_Delete)

        self.assertEqual(1, self.table.deletes)


if __name__ == "__main__":
    unittest.main()
