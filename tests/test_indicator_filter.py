"""Фильтр показателей: поиск и разделы (FUNC-10).

Диалог строил по чекбоксу на каждую позицию в одном вертикальном списке.
Показателей в справочнике под сотню, названия различаются хвостом
(«…— Пассажиры отправленные, чел.» против «…— Пассажиры принятые, чел.»), и
найти нужную строку прокруткой было нельзя.

Разделы берутся из названия, а не из `Indicator.parent_id`, как предполагал
разбор: в справочнике родитель не заполнен ни у одной записи — импортёр заводит
показатели плоским списком. Проверки ниже идут на подписях того же вида, что
ставит разбор бланка 15-ГА.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


if HAS_QT:
    from forms.widgets.multi_select_filter_button import (
        MultiSelectFilterButton,
        group_items,
        split_group,
        worth_grouping,
    )

# Подписи ровно того вида, что приходят из справочника: раздел, длинное тире,
# название графы. Разделы намеренно повторяются — на этом и держится поиск.
SECTIONS = ("Внутренние регулярные", "Внутренние нерегулярные", "Международные регулярные")
COLUMNS = ("Пассажиры отправленные, чел.", "Пассажиры принятые, чел.", "Груз отгружено, т")

INDICATORS = [
    (row * 10 + col, f"{section} — {column}")
    for row, section in enumerate(SECTIONS)
    for col, column in enumerate(COLUMNS)
]


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SplitGroupTest(unittest.TestCase):
    """Раздел выделяется из подписи, а не угадывается."""

    def test_label_with_a_section(self):
        self.assertEqual(
            ("Внутренние регулярные", "Пассажиры отправленные, чел."),
            split_group("Внутренние регулярные — Пассажиры отправленные, чел."),
        )

    def test_label_without_a_section_stays_whole(self):
        self.assertEqual((None, "Налет часов"), split_group("Налет часов"))

    def test_short_dash_is_not_a_separator(self):
        """В названиях разделов встречается дефис: «Внутренние - всего (стр.05+стр.06)»."""
        label = "Внутренние - всего (стр.05+стр.06)"
        self.assertEqual((None, label), split_group(label))

    def test_only_the_first_separator_splits(self):
        section, leaf = split_group("Раздел — часть — ещё часть")
        self.assertEqual("Раздел", section)
        self.assertEqual("часть — ещё часть", leaf)

    def test_empty_half_is_not_a_section(self):
        self.assertEqual((None, " — хвост"), split_group(" — хвост"))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GroupItemsTest(unittest.TestCase):
    def test_sections_keep_the_order_of_appearance(self):
        groups = group_items(INDICATORS)

        self.assertEqual(list(SECTIONS), [name for name, _ in groups])

    def test_every_indicator_lands_in_its_section(self):
        groups = dict(group_items(INDICATORS))

        self.assertEqual(list(COLUMNS),
                         [leaf for _, leaf in groups["Внутренние регулярные"]])

    def test_a_single_section_is_not_worth_showing(self):
        """Кнопкой выбирают и авиакомпании — там лишний уровень только мешает."""
        self.assertFalse(worth_grouping(group_items([(1, "Первая АК"), (2, "Вторая АК")])))
        self.assertFalse(worth_grouping(group_items([(1, "Раздел — а"), (2, "Раздел — б")])))
        self.assertTrue(worth_grouping(group_items(INDICATORS)))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DialogCase(unittest.TestCase):
    def make_dialog(self, items=None, selected=None):
        button = MultiSelectFilterButton("Показатели")
        button.set_items(items if items is not None else INDICATORS)
        if selected:
            button._selected = set(selected)
        # Кнопка держится за тестом: диалог — её потомок, и без ссылки Qt снесёт
        # его вместе с кнопкой, как только та уйдёт в мусор.
        self._buttons.append(button)
        return button, button.make_dialog()

    def setUp(self):
        self._buttons = []

    def top_level(self, dialog):
        return [dialog.tree.topLevelItem(i).text(0)
                for i in range(dialog.tree.topLevelItemCount())]


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SearchNarrowsTheListTest(DialogCase):
    """Главное, ради чего пункт заведён: нужную строку можно найти, а не искать."""

    def test_query_leaves_only_matching_rows(self):
        _, dialog = self.make_dialog()

        dialog.search.setText("отправленные")

        self.assertEqual(len(SECTIONS), len(dialog.visible_ids()))

    def test_query_is_case_insensitive(self):
        _, dialog = self.make_dialog()

        dialog.search.setText("ГРУЗ ОТГРУЖЕНО")

        self.assertEqual(len(SECTIONS), len(dialog.visible_ids()))

    def test_section_name_shows_the_whole_section(self):
        _, dialog = self.make_dialog()

        dialog.search.setText("Международные регулярные")

        self.assertEqual(len(COLUMNS), len(dialog.visible_ids()))

    def test_section_with_no_matches_is_hidden_entirely(self):
        _, dialog = self.make_dialog()

        dialog.search.setText("Международные регулярные")

        shown = [item.text(0) for item in dialog._groups if not item.isHidden()]
        self.assertEqual(["Международные регулярные"], shown)

    def test_clearing_the_query_brings_everything_back(self):
        _, dialog = self.make_dialog()
        dialog.search.setText("отправленные")

        dialog.search.setText("")

        self.assertEqual(len(INDICATORS), len(dialog.visible_ids()))

    def test_counter_reports_what_is_shown(self):
        _, dialog = self.make_dialog()

        dialog.search.setText("отправленные")

        self.assertEqual(f"Показано: {len(SECTIONS)} из {len(INDICATORS)}",
                         dialog.counter.text())

    def test_nothing_found_hides_every_section(self):
        _, dialog = self.make_dialog()

        dialog.search.setText("такого показателя нет")

        self.assertEqual([], dialog.visible_ids())
        self.assertTrue(all(item.isHidden() for item in dialog._groups))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SectionsAreShownWhenTheyHelpTest(DialogCase):
    def test_indicators_are_split_into_sections(self):
        _, dialog = self.make_dialog()

        self.assertEqual(list(SECTIONS), self.top_level(dialog))

    def test_flat_list_has_no_section_level(self):
        _, dialog = self.make_dialog([(1, "Внутренние"), (2, "Международные")])

        self.assertEqual([], dialog._groups)
        self.assertEqual(["Внутренние", "Международные"], self.top_level(dialog))

    def test_flat_list_keeps_the_whole_label(self):
        """Единственный раздел не показывается — но и не отрезается от подписи."""
        _, dialog = self.make_dialog([(1, "Раздел — а"), (2, "Раздел — б")])

        self.assertEqual(["Раздел — а", "Раздел — б"], self.top_level(dialog))

    def test_section_switches_all_of_its_rows(self):
        _, dialog = self.make_dialog()
        first_section = dialog._groups[0]

        first_section.setCheckState(0, Qt.CheckState.Unchecked)

        self.assertEqual(len(INDICATORS) - len(COLUMNS), len(dialog.checked_ids()))

    def test_section_reflects_a_partial_choice(self):
        _, dialog = self.make_dialog()
        first_section = dialog._groups[0]
        first_section.setCheckState(0, Qt.CheckState.Unchecked)

        first_section.child(0).setCheckState(0, Qt.CheckState.Checked)

        self.assertEqual(Qt.CheckState.PartiallyChecked, first_section.checkState(0))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class BulkButtonsFollowTheSearchTest(DialogCase):
    """«Выбрать все» относится к найденному — иначе поиск не помогает выбирать."""

    def test_clearing_touches_only_the_rows_on_screen(self):
        _, dialog = self.make_dialog()
        dialog.search.setText("отправленные")

        dialog.check_visible(False)

        self.assertEqual(len(INDICATORS) - len(SECTIONS), len(dialog.checked_ids()))

    def test_selecting_touches_only_the_rows_on_screen(self):
        _, dialog = self.make_dialog()
        dialog.check_visible(False)
        dialog.search.setText("отправленные")

        dialog.check_visible(True)

        self.assertEqual(len(SECTIONS), len(dialog.checked_ids()))

    def test_without_a_search_the_buttons_take_everything(self):
        _, dialog = self.make_dialog()

        dialog.check_visible(False)

        self.assertEqual(set(), dialog.checked_ids())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DialogStartsFromTheCurrentChoiceTest(DialogCase):
    def test_empty_choice_shows_everything_checked(self):
        """Пустой выбор означает «все»: снимать галочки понятнее, чем ставить с нуля."""
        _, dialog = self.make_dialog()

        self.assertEqual({v for v, _ in INDICATORS}, dialog.checked_ids())

    def test_previous_choice_is_restored(self):
        chosen = {INDICATORS[0][0], INDICATORS[4][0]}
        _, dialog = self.make_dialog(selected=chosen)

        self.assertEqual(chosen, dialog.checked_ids())

    def test_choice_survives_reopening_the_dialog(self):
        button, dialog = self.make_dialog()
        dialog.check_visible(False)
        button._selected = dialog.checked_ids() | {INDICATORS[2][0]}

        reopened = button.make_dialog()

        self.assertEqual({INDICATORS[2][0]}, reopened.checked_ids())


if __name__ == "__main__":
    unittest.main()
