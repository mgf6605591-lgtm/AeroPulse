"""Итог импорта — тип, а не словарь (ARCH-18).

Проверяется не поведение импорта — оно закреплено в `test_import.py` и
`test_import_gate.py`, — а само свойство, ради которого словарь заменён типом:
**опечатка обязана падать**. Прежде `result.get("succes")` возвращал `None`, и
удачная загрузка молча превращалась в неудачную; ни линтер, ни тест, написанный
теми же ключами, этого не видели.
"""
import dataclasses
import re
import unittest
from pathlib import Path

from importers.data_importer import DataImporter
from services.import_outcome import ImportOutcome, PeriodRequired, failure, replace

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TypoIsAnErrorTest(unittest.TestCase):
    """То, ради чего пункт и делался."""

    def test_unknown_field_is_refused_at_construction(self):
        with self.assertRaises(TypeError):
            ImportOutcome(success=True, mesage="опечатка в имени поля")

    def test_unknown_field_is_refused_in_failure_too(self):
        """`failure()` — та же дверь, и закрыта она так же."""
        with self.assertRaises(TypeError):
            failure("причина", sourse_file="опечатка")

    def test_reading_a_missing_field_raises(self):
        outcome = ImportOutcome(success=True)
        # Имя через переменную: обращение к опечатке прямо в коде теста линтер
        # считает бесполезным выражением, а `getattr` с литералом — лишним.
        misspelled = "succes"

        with self.assertRaises(AttributeError):
            getattr(outcome, misspelled)

    def test_outcome_does_not_change_after_it_is_built(self):
        """Итог собирают четыре слоя; менять чужие поля на ходу они не должны."""
        outcome = ImportOutcome(success=True)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            outcome.success = False


class PeriodRequiredTest(unittest.TestCase):
    """Требование спросить период — тип, а не булев ключ среди девяти других."""

    def test_it_is_an_outcome(self):
        """Кто спрашивать не станет, покажет его как обычный отказ."""
        outcome = PeriodRequired(message="период не прочитан")

        self.assertIsInstance(outcome, ImportOutcome)
        self.assertFalse(outcome.success)

    def test_a_plain_outcome_is_not_mistaken_for_it(self):
        self.assertNotIsInstance(failure("что-то другое"), PeriodRequired)

    def test_what_was_read_is_carried_for_the_dialog(self):
        """Год прочитался, месяц нет: человеку незачем вводить заново оба."""
        outcome = PeriodRequired(source_file="а.xlsx", month=None, year=2025)

        self.assertIsNone(outcome.month)
        self.assertEqual(2025, outcome.year)

    def test_the_kind_survives_replace(self):
        """`ImportService` дописывает поля через `replace` — тип обязан устоять."""
        filled = replace(PeriodRequired(message="?"), source_file="а.xlsx")

        self.assertIsInstance(filled, PeriodRequired)
        self.assertEqual("а.xlsx", filled.source_file)


class ImporterReturnsTheTypeTest(unittest.TestCase):
    def test_success_is_an_outcome(self):
        result = DataImporter._import_result(2, 1, 0, created=["АК"], register="авиакомпаний")

        self.assertIsInstance(result, ImportOutcome)
        self.assertTrue(result.success)
        self.assertEqual((2, 1), (result.imported, result.updated))
        self.assertEqual(("АК",), result.created_entities)

    def test_zero_rows_is_still_a_refusal(self):
        """DATA-4 держится и на типе: ноль записей — отказ, а не зелёное «готово»."""
        result = DataImporter._import_result(0, 0)

        self.assertFalse(result.success)
        self.assertEqual(0, result.imported)


class NoResultDictsLeftTest(unittest.TestCase):
    """Проверка на будущее: следующий ключ не должен приехать обратно.

    Ищется строковый литерал `'success'` — тот самый ключ, вокруг которого
    словарь и собирался. Поля типа так не пишутся, поэтому совпадение означает
    ровно одно: где-то снова собирают результат вручную.
    """

    PIPELINE = (
        "importers/data_importer.py",
        "services/import_service.py",
        "forms/import_runner.py",
        "forms/mainWin.py",
    )

    def test_the_pipeline_builds_no_result_dicts(self):
        quoted_success = re.compile(r"""["']success["']""")
        offenders = [
            name for name in self.PIPELINE
            if quoted_success.search((PROJECT_ROOT / name).read_text(encoding="utf-8"))
        ]
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
