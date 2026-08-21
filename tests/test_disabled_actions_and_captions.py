"""Недоступные действия объясняют себя, а подписи кнопок — по-русски.

Обе проверки нашлись прогоном самой программы, а не чтением кода.

Кнопка «Удалить выбранное» включалась по одному только режиму отображения: в
подробном она была нажимаема всегда, в том числе когда не выделено ни строки, —
и нажатие в этом случае не делало ничего и ничего не говорило. Правило проекта
обратное: недоступное действие остаётся видимым и называет причину.

Стандартные кнопки `QDialogButtonBox` Qt подписывает сама, и без файла перевода
подписи остаются английскими: «Close» в окне справочников стояло посреди
русского интерфейса. Перевод в сборку не входит, поэтому подписи задаются свои —
`forms.widgets.dialog_buttons.set_caption` для того и заведён.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QItemSelectionModel
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None

# Подписи, которые Qt ставит стандартным кнопкам сама.
QT_DEFAULT_CAPTIONS = {"OK", "Cancel", "Close", "&OK", "&Cancel", "&Close"}


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DeleteButtonNeedsSelectionTest(unittest.TestCase):
    """Кнопка удаления доступна только когда есть что удалять."""

    def setUp(self):
        from controllers.detail_rows import DetailRow
        from forms.widgets.data_table_widget import DataTableWidget

        self.widget = DataTableWidget()
        self.addCleanup(self.widget.deleteLater)
        self.widget.detail_model.setHeaders(["ID", "Показатель"])
        self.widget.detail_model.setColumnAttributes(["id", "indicator"])
        self.widget.detail_model.set_source_data([
            DetailRow(id=1, entity_name="АК", entity_code="AAA",
                      indicator="Самолето-километры", measure="тыс.сам.-км",
                      month=None, year=2025, value=None,
                      route_type=None, regularity=None),
        ])

    def select_first_row(self):
        table = self.widget.get_table_view()
        table.selectionModel().select(
            self.widget.detail_model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    def test_disabled_in_pivot_mode(self):
        self.assertFalse(self.widget.delete_btn.isEnabled())

    def test_pivot_mode_explains_itself(self):
        """Причина написана на самой кнопке, а не подразумевается."""
        self.assertIn("подробном режиме", self.widget.delete_btn.toolTip())

    def test_detail_mode_without_selection_stays_disabled(self):
        self.widget.radio_detail.setChecked(True)

        self.assertFalse(self.widget.delete_btn.isEnabled())

    def test_detail_mode_without_selection_asks_for_one(self):
        self.widget.radio_detail.setChecked(True)

        self.assertIn("Выделите", self.widget.delete_btn.toolTip())

    def test_selection_enables_the_button(self):
        self.widget.radio_detail.setChecked(True)

        self.select_first_row()

        self.assertTrue(self.widget.delete_btn.isEnabled())

    def test_enabled_button_has_nothing_to_explain(self):
        self.widget.radio_detail.setChecked(True)
        self.select_first_row()

        self.assertEqual("", self.widget.delete_btn.toolTip())

    def test_clearing_the_selection_disables_it_again(self):
        self.widget.radio_detail.setChecked(True)
        self.select_first_row()

        self.widget.get_table_view().selectionModel().clearSelection()

        self.assertFalse(self.widget.delete_btn.isEnabled())

    def test_selection_survives_the_switch_to_pivot(self):
        """Строка выделена, но свод показывает суммы — удалять по-прежнему нечего."""
        self.widget.radio_detail.setChecked(True)
        self.select_first_row()

        self.widget.radio_pivot.setChecked(True)

        self.assertFalse(self.widget.delete_btn.isEnabled())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DialogCaptionsAreRussianTest(unittest.TestCase):
    """Ни одной кнопки с подписью, которую поставила Qt."""

    def captions(self, widget) -> list[str]:
        found = []
        for box in widget.findChildren(QDialogButtonBox):
            for button in box.buttons():
                found.append(button.text())
        return found

    def assertNoQtCaptions(self, widget):
        self.addCleanup(widget.deleteLater)
        captions = self.captions(widget)
        self.assertTrue(captions, "в окне не нашлось ни одной стандартной кнопки")
        left = [text for text in captions if text in QT_DEFAULT_CAPTIONS]
        self.assertEqual([], left, f"английские подписи: {left}; всего кнопок: {captions}")

    def test_reference_dialog(self):
        from forms.widgets.reference_dialog import ReferenceDialog

        self.assertNoQtCaptions(ReferenceDialog())

    def test_reference_editor(self):
        from forms.widgets.reference_dialog import ReferenceEditor
        from services.reference_service import ReferenceService

        self.assertNoQtCaptions(ReferenceEditor(ReferenceService.kind("locality")))

    def test_import_dialog(self):
        from forms.widgets.import_dialog import ImportDialog

        self.assertNoQtCaptions(ImportDialog())

    def test_period_dialog(self):
        from forms.widgets.period_dialog import PeriodDialog

        self.assertNoQtCaptions(PeriodDialog("отчёт.xlsx"))

    def test_multi_select_dialog(self):
        from forms.widgets.multi_select_filter_button import MultiSelectDialog

        self.assertNoQtCaptions(MultiSelectDialog("Показатели", [(1, "Первый")], set()))


if __name__ == "__main__":
    unittest.main()
