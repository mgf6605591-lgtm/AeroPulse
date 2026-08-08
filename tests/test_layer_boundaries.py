"""Слой `controllers/` не знает про интерфейс (ARCH-2).

Экспортёр сам обходил `QTableView` и сам показывал `QMessageBox`: слой, который
по замыслу интерфейса не касается, был кодом интерфейса. Позвать его из теста
или из командной строки было нельзя — модальное окно остановило бы и то и другое,
а об ошибке он сообщал не вызывающему, а пользователю, возвращая наружу `False`
без причины.

Сборка книги теперь принимает готовые заголовки и строки значений и об ошибке
сообщает исключением. Чтение модели и окна сообщений — в `forms/table_export.py`.

Проверяется так же, как граница пакета данных в ARCH-3: запретом импорта в
отдельном процессе, а не разглядыванием кода.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import load_workbook

from controllers.export_controller import ExportController

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Запрет ставится подменой в sys.modules: `import PyQt6` падает и в том случае,
# если пакет установлен, — а он установлен, иначе половина прогона пропускалась бы.
_IMPORT_CONTROLLERS_WITHOUT_QT = """
import sys
sys.modules['PyQt6'] = None
try:
    import PyQt6  # noqa: F401
except ImportError:
    pass
else:
    raise AssertionError('запрет на PyQt6 не сработал — проверка ничего не значит')

import controllers.AirlineIndController   # noqa: F401
import controllers.AirportIndController   # noqa: F401
import controllers.UserController         # noqa: F401
import controllers.data_controller        # noqa: F401
import controllers.export_controller      # noqa: F401
import controllers.export_header          # noqa: F401
import controllers.filter_controller      # noqa: F401
import controllers.period_filter          # noqa: F401
import controllers.reference_cache        # noqa: F401
import controllers.report_filters         # noqa: F401
"""


class ControllersNeedNoGuiTest(unittest.TestCase):
    def test_layer_imports_without_pyqt(self):
        result = subprocess.run(
            [sys.executable, "-c", _IMPORT_CONTROLLERS_WITHOUT_QT],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_no_source_in_the_layer_mentions_pyqt(self):
        """Проверка на будущее: следующий диалог не должен приехать обратно."""
        offenders = [
            path.name for path in (PROJECT_ROOT / "controllers").glob("*.py")
            if re.search(r"^\s*(import|from)\s+PyQt6", path.read_text(encoding="utf-8"), re.M)
        ]
        self.assertEqual([], offenders)

    def test_layer_does_not_reach_into_forms(self):
        """Обратная зависимость ушла вместе с чтением модели: роль RAW_VALUE_ROLE — там же, где модели."""
        offenders = [
            path.name for path in (PROJECT_ROOT / "controllers").glob("*.py")
            if re.search(r"^\s*(import|from)\s+forms", path.read_text(encoding="utf-8"), re.M)
        ]
        self.assertEqual([], offenders)


class WorkbookIsWrittenWithoutQtTest(unittest.TestCase):
    """Сборка книги вызывается напрямую — без окна, без модели, без QApplication."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "export.xlsx")

    def write(self, **kwargs):
        ExportController.write_workbook(
            self.path,
            headers=["Показатель", "Январь 2025"],
            rows=[["Самолето-километры", 1234567.0], ["Налет часов", 0.0]],
            **kwargs,
        )
        return load_workbook(self.path).active

    def test_values_reach_the_file(self):
        ws = self.write()

        self.assertEqual("Показатель", ws["A1"].value)
        self.assertEqual("Самолето-километры", ws["A2"].value)
        self.assertEqual(1234567, ws["B2"].value)

    def test_numbers_stay_numbers(self):
        """FUNC-2 держится и без Qt: тип ячейки задаёт сборщик, а не модель."""
        ws = self.write()

        self.assertEqual("n", ws["B2"].data_type)
        self.assertEqual("#,##0", ws["B2"].number_format)

    def test_failure_is_reported_by_an_exception(self):
        """Прежде метод возвращал False и показывал окно: причина не доходила."""
        with self.assertRaises(OSError):
            ExportController.write_workbook(
                os.path.join(self.path, "нет", "такого", "пути.xlsx"),
                headers=["Показатель"],
                rows=[["Самолето-километры"]],
            )


if __name__ == "__main__":
    unittest.main()
