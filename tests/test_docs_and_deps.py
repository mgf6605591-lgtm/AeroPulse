"""Зависимости и документация (INFRA-4, INFRA-6).

`scikit-learn` числился в зависимостях, не используясь ни разу: десятки мегабайт
в дистрибутиве и лишняя поверхность обновлений безопасности. README состоял из
заголовка и строки «Jgbcfuby» — слова «Описание», набранного в латинской
раскладке.

Документация проверяется не на наличие, а на согласие с кодом: названия файлов,
каталогов и таблиц берутся из самого приложения. Описание, разошедшееся с
программой, вреднее отсутствующего — по нему принимают решения.
"""

import re
import unittest
from pathlib import Path

from db.backup import BACKUP_DIR_NAME, KEEP_BACKUPS
from db.models.entities import Base
from utils.logging_setup import LOG_FILE_NAME
from utils.passwords import MIN_PASSWORD_LENGTH

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
README = PROJECT_ROOT / "README.md"

PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+$")


def requirement_names():
    """Имена пакетов из requirements.txt, без комментариев и пустых строк."""
    names = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if line:
            names.append(line.split("==")[0].lower())
    return names


class RequirementsCarryNothingExtraTest(unittest.TestCase):
    """INFRA-4: тяжёлая зависимость, которой никто не пользовался."""

    def test_scikit_learn_is_gone(self):
        self.assertNotIn("scikit-learn", requirement_names())

    def test_nothing_imports_sklearn(self):
        """Причина, по которой её и убрали, — проверяется по исходникам."""
        offenders = [
            path.relative_to(PROJECT_ROOT)
            for path in PROJECT_ROOT.rglob("*.py")
            if ".venv" not in path.parts
            and re.search(r"^\s*(import|from)\s+sklearn\b",
                          path.read_text(encoding="utf-8"), re.M)
        ]
        self.assertEqual([], offenders)

    def test_every_line_is_pinned(self):
        """Файл собран заморозкой: сборка exe должна воспроизводиться."""
        loose = [
            raw.strip()
            for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if raw.split("#")[0].strip() and not PINNED.match(raw.split("#")[0].strip())
        ]
        self.assertEqual([], loose)


class XlrdIsNotDeadWeightTest(unittest.TestCase):
    """xlrd не импортируется ни разу — и всё-таки нужен.

    Формат книги выбирает сама pandas: `.xlsx` читает openpyxl, `.xls` — xlrd.
    Импорт принимает оба (`services/parse_service.py`), поэтому убрать пакет по
    отсутствию импортов значило бы молча отнять поддержку `.xls`. Пункт реестра
    ставил его «под вопрос» — вот ответ, и он проверяемый.
    """

    def test_xlrd_is_still_required(self):
        self.assertIn("xlrd", requirement_names())

    def test_pandas_still_reads_xls_through_it(self):
        """Если pandas когда-нибудь откажется от xlrd, пункт нужно пересмотреть."""
        from pandas.io.excel._base import ExcelFile

        self.assertIn("xlrd", ExcelFile._engines)

    def test_import_accepts_xls(self):
        source = (PROJECT_ROOT / "services" / "parse_service.py").read_text(encoding="utf-8")

        self.assertIn(".xls'", source)


class ReadmeDescribesTheProgramTest(unittest.TestCase):
    """INFRA-6: содержимым было слово «Описание» в латинской раскладке."""

    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_placeholder_is_gone(self):
        self.assertNotIn("Jgbcfuby", self.text)

    def test_both_forms_are_named(self):
        self.assertIn("12-ГА", self.text)
        self.assertIn("15-ГА", self.text)

    def test_entry_point_and_build_are_documented(self):
        self.assertIn("python main.py", self.text)
        self.assertIn("pyinstaller aeropulse.spec", self.text)
        self.assertTrue((PROJECT_ROOT / "aeropulse.spec").exists())

    def test_test_command_actually_works(self):
        """Команда прогона тестов приведена той же, какой её запускает CI."""
        self.assertIn("python -m unittest discover -s tests -t .", self.text)
        ci = (PROJECT_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover -s tests -t .", ci)


class ReadmeAgreesWithTheCodeTest(unittest.TestCase):
    """Названия и числа в описании берутся из приложения, а не написаны на память."""

    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_log_file_is_named_correctly(self):
        self.assertIn(LOG_FILE_NAME, self.text)

    def test_backups_are_described_as_they_work(self):
        self.assertIn(f"db/{BACKUP_DIR_NAME}/", self.text)
        self.assertIn(f"последние {KEEP_BACKUPS}", self.text)

    def test_password_rule_matches_the_service(self):
        self.assertIn(f"не короче {MIN_PASSWORD_LENGTH} символов", self.text)

    def test_every_table_is_described(self):
        """Схема разойдётся с описанием молча — если её не сверять."""
        described = set(re.findall(r"`(\w+)`", self.text))
        missing = sorted(set(Base.metadata.tables) - described)

        self.assertEqual([], missing)

    def test_no_table_is_invented(self):
        """Обратная сторона: в описании нет таблиц, которых в схеме не бывает."""
        schema_section = self.text.split("## Схема базы")[1].split("##")[0]
        mentioned = set(re.findall(r"`(\w+)`", schema_section))
        # Из выделенного моноширинным в этом разделе таблицами не являются
        # только тип значения и формат хранения.
        invented = sorted(mentioned - set(Base.metadata.tables) - {"Decimal", "float"})

        self.assertEqual([], invented)


class LicenseIsDeliberatelyAbsentTest(unittest.TestCase):
    """Лицензии нет по решению, а не по недосмотру.

    Пункт реестра требовал её добавить; решено не добавлять. Проверка стоит,
    чтобы следующий разбор не завёл пункт заново, увидев отсутствие файла: в
    README сказано прямо, что права сохраняются за автором.
    """

    def test_readme_states_the_terms(self):
        text = README.read_text(encoding="utf-8")

        self.assertIn("## Лицензия", text)
        self.assertIn("Лицензия не выбрана", text)

    def test_no_license_file_pretends_otherwise(self):
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
            self.assertFalse((PROJECT_ROOT / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
