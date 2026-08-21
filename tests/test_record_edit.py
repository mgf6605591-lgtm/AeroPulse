"""Правка отчётной строки: служба, диалог и то, чем её вызывают.

Правят значение и период — то, в чём ошибается бланк. Показатель, предприятие и
рейс строку определяют: сменить их значит завести другую запись, а не исправить
эту, поэтому в диалоге они только показаны.

Порядок «копия базы → изменение → журнал» проверяется прогоном, как и у удаления
(`tests/test_deletion.py`): прежнего значения после записи не остаётся нигде,
кроме копии и журнала. Главная из проверок ниже — `test_backup_predates_the_edit`:
копия, снятая после изменения, выглядит как копия, но не восстанавливает ничего.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import sqlite3
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy.orm import sessionmaker

from db.models.entities import (
    Airline,
    AirlineIndicators,
    Airport,
    AirportIndicators,
    ImportLog,
    Indicator,
    Locality,
    Route,
    Shipping,
)
from db.models.enums import Months, RouteType, ShippingRegularity
from services.edit_service import (
    BackupUnavailable,
    PeriodTaken,
    RecordGone,
    update_indicator,
)
from tests.support import MigratedDbCase

try:
    from PyQt6.QtCore import QItemSelectionModel
    from PyQt6.QtWidgets import QApplication, QDialog
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


# --- служба -----------------------------------------------------------------

class EditCase(MigratedDbCase):
    """Две строки 12-ГА (январь и февраль) и одна 15-ГА на своей базе."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.add(Route(id=1, type=RouteType.trunk, regularity=ShippingRegularity.regular))
            session.add(Shipping(id=1, route_id=1, airline_id=1))
            session.add(Locality(id=1, name="Город"))
            session.add(Airport(id=1, code="XXX", name="Аэропорт", locality_id=1))
            session.add(Indicator(id=1, name="Налет часов", code="356", measure="час."))
            session.add(Indicator(id=2, name="Самолето-километры", code="357", measure="тыс."))
            session.commit()
        with self.Session() as session:
            session.add(AirlineIndicators(
                id=1, indicator_id=1, shipping_id=1,
                month=Months.January, year=2025, value=Decimal("81.07"),
            ))
            session.add(AirlineIndicators(
                id=2, indicator_id=1, shipping_id=1,
                month=Months.February, year=2025, value=Decimal("25.74"),
            ))
            session.add(AirportIndicators(
                id=1, indicator_id=1, airport_id=1,
                month=Months.January, year=2025, value=Decimal("9"),
            ))
            session.commit()

        # Служба и журнал открывают свои сессии; база у теста своя.
        for target in ("services.edit_service.get_session",
                       "services.journal_service.get_session"):
            patcher = patch(target, self.Session)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Копия снимается с того файла, который назовёт db_path().
        path_patch = patch("services.indicator_records.db_path", lambda: Path(self.db_path))
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def airline_row(self, row_id: int = 1):
        with self.Session() as session:
            return session.get(AirlineIndicators, row_id)

    def airport_row(self, row_id: int = 1):
        with self.Session() as session:
            return session.get(AirportIndicators, row_id)

    def journal_rows(self):
        with self.Session() as session:
            return session.query(ImportLog).filter(ImportLog.kind == "replace").all()

    def edit(self, row_id: int = 1, *, month=Months.January, year=2025,
             value="81.07", **kwargs):
        return update_indicator(
            "airline", row_id,
            month=month, year=year, value=Decimal(value), **kwargs,
        )


class ValueAndPeriodAreWrittenTest(EditCase):
    def test_value_is_replaced(self):
        result = self.edit(value="90.5")

        self.assertTrue(result.changed)
        self.assertEqual(Decimal("90.5"), self.airline_row().value)

    def test_decimals_survive_the_trip(self):
        """Значение хранится десятичным ровно затем, чтобы не округляться."""
        self.edit(value="5896.29")

        self.assertEqual(Decimal("5896.29"), self.airline_row().value)

    def test_period_is_replaced(self):
        result = self.edit(month=Months.March, year=2024, value="81.07")

        self.assertTrue(result.changed)
        row = self.airline_row()
        self.assertEqual((Months.March, 2024), (row.month, row.year))

    def test_airport_rows_are_edited_by_their_own_kind(self):
        update_indicator("airport", 1, month=Months.May, year=2025, value=Decimal("11"))

        row = self.airport_row()
        self.assertEqual((Months.May, Decimal("11")), (row.month, row.value))
        # Строка 12-ГА с тем же id осталась январской.
        self.assertEqual(Months.January, self.airline_row().month)

    def test_unknown_kind_is_refused_and_changes_nothing(self):
        with self.assertRaises(ValueError):
            update_indicator("самолёты", 1, month=Months.May, year=2025, value=Decimal("1"))

        self.assertEqual(Decimal("81.07"), self.airline_row().value)

    def test_a_deleted_record_is_named_as_such(self):
        """Строку могли удалить в другом окне, пока диалог был открыт."""
        with self.assertRaises(RecordGone):
            self.edit(row_id=999)

    def test_an_edit_that_changes_nothing_is_not_an_edit(self):
        result = self.edit(month=Months.January, year=2025, value="81.07")

        self.assertFalse(result.changed)
        self.assertIsNone(result.backup)
        self.assertEqual([], self.journal_rows())


class TakenPeriodTest(EditCase):
    """Ключ отчётной строки — показатель, предприятие, месяц и год."""

    def test_moving_onto_an_existing_period_is_refused(self):
        with self.assertRaises(PeriodTaken):
            self.edit(row_id=1, month=Months.February, year=2025, value="81.07")

    def test_the_refusal_changes_nothing(self):
        with self.assertRaises(PeriodTaken):
            self.edit(row_id=1, month=Months.February, year=2025, value="1")

        row = self.airline_row(1)
        self.assertEqual((Months.January, Decimal("81.07")), (row.month, row.value))
        self.assertEqual(Decimal("25.74"), self.airline_row(2).value)

    def test_the_refusal_names_the_period(self):
        with self.assertRaises(PeriodTaken) as caught:
            self.edit(row_id=1, month=Months.February, year=2025, value="81.07")

        self.assertIn("Февраль 2025", str(caught.exception))

    def test_the_records_own_period_is_not_a_conflict(self):
        """Правка одного значения оставляет период на месте — сама с собой не спорит."""
        self.edit(row_id=1, month=Months.January, year=2025, value="7")

        self.assertEqual(Decimal("7"), self.airline_row(1).value)

    def test_another_indicator_may_share_the_period(self):
        """Занят период парой «показатель + предприятие», а не одним периодом."""
        with self.Session() as session:
            session.add(AirlineIndicators(
                id=3, indicator_id=2, shipping_id=1,
                month=Months.February, year=2025, value=Decimal("3"),
            ))
            session.commit()

        self.edit(row_id=1, month=Months.March, year=2025, value="81.07")

        self.assertEqual(Months.March, self.airline_row(1).month)


class BackupTest(EditCase):
    def test_backup_predates_the_edit(self):
        """Копия, снятая после правки, не восстанавливает прежнее значение."""
        result = self.edit(value="90.5")

        self.assertIsNotNone(result.backup)
        connection = sqlite3.connect(str(result.backup))
        try:
            saved = connection.execute(
                "SELECT value FROM airlineInd WHERE id = 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(("81.07",), saved)

    def test_backup_failure_stops_the_edit(self):
        with patch("services.indicator_records.make_backup", side_effect=OSError("нет места")):
            with self.assertRaises(BackupUnavailable):
                self.edit(value="90.5")

        self.assertEqual(Decimal("81.07"), self.airline_row().value)
        self.assertEqual([], self.journal_rows())

    def test_the_reason_travels_with_the_refusal(self):
        with patch("services.indicator_records.make_backup", side_effect=OSError("нет места")):
            with self.assertRaises(BackupUnavailable) as caught:
                self.edit(value="90.5")

        self.assertIn("нет места", str(caught.exception))

    def test_an_explicit_waiver_lets_the_edit_through(self):
        """Так окно поступает, когда человек ответил «изменить всё равно»."""
        with patch("services.indicator_records.make_backup", side_effect=OSError("нет места")):
            result = self.edit(value="90.5", require_backup=False)

        self.assertIsNone(result.backup)
        self.assertTrue(result.changed)
        self.assertEqual(Decimal("90.5"), self.airline_row().value)

    def test_a_pointless_edit_costs_no_copy(self):
        """Копия базы — файл на диск: снимать его, чтобы ничего не изменить, незачем."""
        with patch("services.indicator_records.make_backup") as backup:
            self.edit(value="81.07")

        backup.assert_not_called()

    def test_a_refused_edit_costs_no_copy(self):
        with patch("services.indicator_records.make_backup") as backup:
            with self.assertRaises(PeriodTaken):
                self.edit(month=Months.February, year=2025, value="1")

        backup.assert_not_called()


class JournalTest(EditCase):
    def test_edit_leaves_a_row(self):
        self.edit(value="90.5", user="ваня")

        (row,) = self.journal_rows()
        self.assertEqual(1, row.updated)
        self.assertEqual("airline", row.entity_type)
        self.assertEqual("ваня", row.user)

    def test_the_journal_keeps_what_was_replaced(self):
        """Прежнего значения после записи не остаётся больше нигде."""
        self.edit(value="90.5")

        (row,) = self.journal_rows()
        self.assertIn("81.07", row.message)
        self.assertIn("90.5", row.message)

    def test_the_journal_names_the_record(self):
        self.edit(value="90.5")

        (row,) = self.journal_rows()
        self.assertIn("запись 1", row.message)

    def test_a_moved_period_is_written_down_too(self):
        self.edit(month=Months.March, year=2024, value="81.07")

        (row,) = self.journal_rows()
        self.assertIn("Январь 2025", row.message)
        self.assertIn("Март 2024", row.message)
        self.assertEqual((Months.March, 2024), (row.month, row.year))


# --- разбор введённого числа ------------------------------------------------

class ParseNumberTest(unittest.TestCase):
    """Обратная сторона показа: правят значение в том же виде, в каком видят."""

    def parse(self, text: str) -> Decimal:
        from forms.models.formatting import parse_number_ru

        return parse_number_ru(text)

    def test_russian_notation_is_understood(self):
        self.assertEqual(Decimal("1234.57"), self.parse("1 234,57"))

    def test_a_dot_works_too(self):
        """На цифровой клавиатуре запятой нет."""
        self.assertEqual(Decimal("1234.57"), self.parse("1234.57"))

    def test_spaces_around_are_ignored(self):
        self.assertEqual(Decimal("81.07"), self.parse("  81,07  "))

    def test_non_breaking_space_is_a_separator_too(self):
        """Так разряды разделяет Excel, а оттуда значение и приезжает."""
        self.assertEqual(Decimal("1234"), self.parse("1 234"))

    def test_precision_is_not_lost(self):
        """Через float это число превратилось бы в двоичное приближение."""
        self.assertEqual(Decimal("5896.29"), self.parse("5896,29"))

    def test_words_are_refused(self):
        with self.assertRaises(ValueError):
            self.parse("восемьдесят")

    def test_emptiness_is_refused(self):
        with self.assertRaises(ValueError):
            self.parse("   ")

    def test_infinity_is_not_a_number_here(self):
        """`Decimal` понимает «inf», отчётность — нет."""
        with self.assertRaises(ValueError):
            self.parse("inf")


# --- диалог -----------------------------------------------------------------

def detail_row(**kwargs):
    from controllers.detail_rows import DetailRow

    fields = dict(
        id=7, entity_name="Тестовая АК", entity_code="AAA",
        indicator="Налет часов", measure="час.",
        month=Months.January, year=2025, value=Decimal("81.07"),
        route_type=RouteType.local, regularity=ShippingRegularity.irregular,
    )
    fields.update(kwargs)
    return DetailRow(**fields)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class EditDialogTest(unittest.TestCase):
    """Что диалог показывает, что отдаёт и чего не выпускает наружу."""

    def dialog(self, **kwargs):
        from forms.widgets.record_edit_dialog import RecordEditDialog

        dialog = RecordEditDialog(detail_row(**kwargs))
        self.addCleanup(dialog.deleteLater)
        return dialog

    def labels(self, dialog) -> str:
        from PyQt6.QtWidgets import QLabel

        return "\n".join(label.text() for label in dialog.findChildren(QLabel))

    def test_it_opens_on_the_records_own_period(self):
        dialog = self.dialog(month=Months.March, year=2024)

        self.assertEqual(Months.March, dialog.month())
        self.assertEqual(2024, dialog.year())

    def test_it_opens_on_the_records_own_value(self):
        dialog = self.dialog(value=Decimal("81.07"))

        self.assertEqual("81,07", dialog.value_edit.text())
        self.assertEqual(Decimal("81.07"), dialog.value())

    def test_the_stored_value_is_shown_in_full(self):
        """В таблице значение округлено до сотых; править его так значило бы терять разряды."""
        dialog = self.dialog(value=Decimal("1234.5678"))

        self.assertEqual("1234,5678", dialog.value_edit.text())

    def test_what_the_record_is_stands_in_the_window(self):
        dialog = self.dialog()

        shown = self.labels(dialog)
        for expected in ("Тестовая АК", "Налет часов", "Внутренние", "Не регулярные"):
            with self.subTest(expected=expected):
                self.assertIn(expected, shown)

    def test_airport_rows_show_their_own_fields(self):
        """У 15-ГА рейса нет — пустые графы не показываются вовсе."""
        dialog = self.dialog(route_type=None, regularity=None, locality="Мирный")

        shown = self.labels(dialog)
        self.assertIn("Мирный", shown)
        self.assertNotIn("Тип маршрута", shown)

    def test_an_edited_value_comes_back(self):
        dialog = self.dialog()

        dialog.value_edit.setText("1 234,57")

        self.assertEqual(Decimal("1234.57"), dialog.value())

    def test_a_word_instead_of_a_number_keeps_the_window_open(self):
        """Иначе окно закрылось бы «успешно», а правка сорвалась бы за его пределами."""
        from PyQt6.QtWidgets import QMessageBox

        dialog = self.dialog()
        dialog.value_edit.setText("восемьдесят")

        with patch.object(QMessageBox, "warning") as warned:
            dialog.accept()

        self.assertFalse(dialog.result())
        warned.assert_called_once()

    def test_a_number_closes_it(self):
        dialog = self.dialog()
        dialog.value_edit.setText("90,5")

        dialog.accept()

        self.assertEqual(dialog.DialogCode.Accepted, dialog.result())


# --- чем правку вызывают ----------------------------------------------------

@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class EditIsAskedForByTheTableTest(unittest.TestCase):
    """Кнопка, двойной щелчок и меню называют запись — сам виджет её не правит."""

    def setUp(self):
        from forms.widgets.data_table_widget import DataTableWidget

        self.widget = DataTableWidget()
        self.addCleanup(self.widget.deleteLater)
        self.widget.detail_model.setHeaders(["ID", "Показатель", "Значение"])
        self.widget.detail_model.setColumnAttributes(["id", "indicator", "value"])
        self.rows = [detail_row(id=1), detail_row(id=2, month=Months.February)]
        self.widget.detail_model.set_source_data(self.rows)

        self.asked = []
        self.widget.edit_requested.connect(self.asked.append)

    def select(self, *rows):
        selection = self.widget.get_table_view().selectionModel()
        selection.clearSelection()
        for row in rows:
            selection.select(
                self.widget.detail_model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )

    def test_disabled_in_pivot_mode(self):
        self.assertFalse(self.widget.edit_btn.isEnabled())

    def test_pivot_mode_explains_itself(self):
        self.assertIn("подробном режиме", self.widget.edit_btn.toolTip())

    def test_detail_mode_without_selection_asks_for_one(self):
        self.widget.radio_detail.setChecked(True)

        self.assertFalse(self.widget.edit_btn.isEnabled())
        self.assertIn("Выделите строку", self.widget.edit_btn.toolTip())

    def test_one_row_enables_the_button(self):
        self.widget.radio_detail.setChecked(True)

        self.select(0)

        self.assertTrue(self.widget.edit_btn.isEnabled())
        self.assertEqual("", self.widget.edit_btn.toolTip())

    def test_two_rows_disable_it_with_a_reason(self):
        """Удалить можно пачку, править — только одну запись за раз."""
        self.widget.radio_detail.setChecked(True)

        self.select(0, 1)

        self.assertFalse(self.widget.edit_btn.isEnabled())
        self.assertIn("одну строку", self.widget.edit_btn.toolTip())
        self.assertTrue(self.widget.delete_btn.isEnabled())

    def test_the_button_names_the_selected_record(self):
        self.widget.radio_detail.setChecked(True)
        self.select(1)

        self.widget.edit_btn.click()

        self.assertEqual([self.rows[1]], self.asked)

    def test_a_double_click_names_the_clicked_record(self):
        self.widget.radio_detail.setChecked(True)

        self.widget.get_table_view().doubleClicked.emit(
            self.widget.detail_model.index(1, 2)
        )

        self.assertEqual([self.rows[1]], self.asked)

    def test_a_double_click_in_the_pivot_asks_for_nothing(self):
        """В своде строка — это сумма, а не запись: править нечего."""
        self.widget.get_table_view().doubleClicked.emit(
            self.widget.pivot_model.index(0, 0)
        )

        self.assertEqual([], self.asked)

    def test_the_context_menu_offers_the_edit(self):
        from PyQt6.QtWidgets import QMenu

        self.widget.radio_detail.setChecked(True)
        table = self.widget.get_table_view()
        point = table.visualRect(self.widget.detail_model.index(0, 0)).center()

        captions = []
        with patch.object(QMenu, "exec", lambda menu, *args: captions.extend(
            action.text() for action in menu.actions()
        )):
            table.customContextMenuRequested.emit(point)

        self.assertIn("Редактировать запись", captions)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DetailModeIsNamedByWhatItDoesTest(unittest.TestCase):
    def test_the_switch_mentions_the_edit(self):
        """Подпись «Подробный (с удалением)» перестала быть правдой."""
        from forms.widgets.data_table_widget import DataTableWidget

        widget = DataTableWidget()
        self.addCleanup(widget.deleteLater)

        self.assertIn("правка", widget.radio_detail.text())


# --- окно: диалог, служба, ответы на отказы ---------------------------------

class FakeDialog:
    """Диалог правки, заменённый на его ответы: окну от него нужны четыре метода."""

    accepted = True
    last = None

    def __init__(self, row, parent=None):
        self.row = row
        FakeDialog.last = self

    def exec(self):
        return (QDialog.DialogCode.Accepted if self.accepted
                else QDialog.DialogCode.Rejected)

    def month(self):
        return Months.March

    def year(self):
        return 2024

    def value(self):
        return Decimal("90.5")



if HAS_QT:
    # Ответ диалога окно сверяет с `RecordEditDialog.DialogCode`: у подмены он
    # обязан быть тем же перечислением, иначе сверка ничего не значит.
    FakeDialog.DialogCode = QDialog.DialogCode


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WindowEditsThroughTheServiceTest(unittest.TestCase):
    """Окно спрашивает и показывает итог; копию, изменение и журнал ведёт служба."""

    def setUp(self):
        from PyQt6.QtWidgets import QMainWindow

        from forms.mainWin import MainWindow
        from services.edit_service import EditResult
        from utils.constants import MODE_AIRLINE

        # Окно поднимается без своего `__init__`: ради одного слота незачем
        # поднимать базу, вкладки и таблицы (так же устроен tests/test_entity_from_file.py).
        self.window = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(self.window)
        self.addCleanup(self.window.deleteLater)
        self.window.current_mode = MODE_AIRLINE
        self.window.current_user = type("User", (), {"username": "ваня"})()

        FakeDialog.accepted = True
        self.result = EditResult(changed=True, backup=Path("copy.db"))
        self.update = patch("forms.mainWin.update_indicator",
                            side_effect=lambda *a, **kw: self.result).start()
        self.dialog = patch("forms.mainWin.RecordEditDialog", FakeDialog).start()
        self.reload = patch.object(MainWindow, "_load_initial_data").start()
        self.shown = patch("forms.mainWin.QMessageBox").start()
        self.addCleanup(patch.stopall)

    def edit(self, row=None):
        self.window.edit_record(row or detail_row())

    def test_the_dialog_gets_the_record(self):
        row = detail_row(id=42)

        self.edit(row)

        self.assertIs(row, FakeDialog.last.row)

    def test_what_the_dialog_answered_goes_to_the_service(self):
        self.edit(detail_row(id=42))

        self.update.assert_called_once()
        args, kwargs = self.update.call_args
        self.assertEqual(("airline", 42), args)
        self.assertEqual(Months.March, kwargs["month"])
        self.assertEqual(2024, kwargs["year"])
        self.assertEqual(Decimal("90.5"), kwargs["value"])
        self.assertEqual("ваня", kwargs["user"])
        self.assertTrue(kwargs["require_backup"])

    def test_a_closed_dialog_changes_nothing(self):
        FakeDialog.accepted = False

        self.edit()

        self.update.assert_not_called()

    def test_a_successful_edit_reloads_the_tables(self):
        self.edit()

        self.reload.assert_called_once()

    def test_an_edit_that_changed_nothing_leaves_the_tables_alone(self):
        from services.edit_service import EditResult

        self.result = EditResult(changed=False, backup=None)

        self.edit()

        self.reload.assert_not_called()

    def test_a_taken_period_is_shown_as_a_warning(self):
        self.update.side_effect = PeriodTaken("За Март 2024 такая запись уже есть.")

        self.edit()

        self.shown.warning.assert_called_once()
        self.shown.critical.assert_not_called()
        self.reload.assert_not_called()

    def test_a_vanished_record_is_shown_as_a_warning(self):
        self.update.side_effect = RecordGone("нет такой")

        self.edit()

        self.shown.warning.assert_called_once()
        self.reload.assert_not_called()

    def test_a_failed_backup_is_a_question_and_a_no_stops_the_edit(self):
        """По умолчанию — «нет»: прежнее значение восстановить будет нечем (FUNC-13)."""
        self.update.side_effect = BackupUnavailable("нет места")
        self.shown.question.return_value = self.shown.StandardButton.No

        self.edit()

        self.shown.question.assert_called_once()
        self.assertEqual(1, self.update.call_count)
        self.reload.assert_not_called()

    def test_a_yes_repeats_the_edit_without_the_copy(self):
        from services.edit_service import EditResult

        # Список ответов: первым служба отказывается из-за копии, вторым —
        # соглашается без неё. Исключение в списке `side_effect` возбуждается.
        self.update.side_effect = [
            BackupUnavailable("нет места"),
            EditResult(changed=True, backup=None),
        ]
        self.shown.question.return_value = self.shown.StandardButton.Yes

        self.edit()

        self.assertEqual(2, self.update.call_count)
        self.assertFalse(self.update.call_args.kwargs["require_backup"])
        self.reload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
