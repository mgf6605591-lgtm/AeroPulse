"""Импорт в фоновом потоке: прогресс, отмена, вопрос о периоде (BUG-11).

Цикл по файлам шёл в обработчике нажатия, и на пачке окно переставало
перерисовываться. Проверяется именно это: пока идёт импорт, цикл событий
работает — таймер успевает сработать, — а сам разбор выполняется не в потоке
интерфейса.

Служба импорта подменена заглушкой: пункт про поток, а не про разбор бланка.
Заглушка спит, потому что мгновенная работа не отличила бы фоновый поток от
обычного вызова.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication, QDialog
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


if HAS_QT:
    from unittest.mock import patch

    from forms.import_runner import ImportRunner


class StubImport:
    """Заглушка `ImportService.import_file`: помнит вызовы и поток каждого."""

    def __init__(self, per_file_seconds=0.1, needs_period=()):
        self.per_file_seconds = per_file_seconds
        self.needs_period = set(needs_period)
        self.calls = []
        self.threads = []

    def __call__(self, file_path, *, entity_type, entity_id, month, year):
        self.calls.append((file_path, month, year))
        self.threads.append(threading.current_thread())
        time.sleep(self.per_file_seconds)

        name = os.path.basename(file_path)
        if file_path in self.needs_period and month is None:
            return {
                "success": False,
                "period_required": True,
                "message": "период не определён",
                "source_file": name,
                "period_month": None,
                "period_year": None,
            }
        return {
            "success": True,
            "message": "загружено строк: 1",
            "source_file": name,
            "period_month": month or "January",
            "period_year": year or 2025,
        }


def fake_period_dialog(accepted: bool, month="March", year=2026, shown=None):
    """Класс-замена `PeriodDialog`: отвечает, не показывая окна."""

    class FakePeriodDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, file_name, month=None, year=None, parent=None):
            if shown is not None:
                shown.append(file_name)

        def exec(self):
            return (QDialog.DialogCode.Accepted if accepted
                    else QDialog.DialogCode.Rejected)

        def get_month(self):
            return month

        def get_year(self):
            return year

    return FakePeriodDialog


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ImportRunnerCase(unittest.TestCase):
    """Пакет из нескольких файлов на подменённой службе импорта."""

    def make_runner(self, paths, stub, period_dialog=None):
        patcher = patch("forms.import_runner.ImportService.import_file", stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        if period_dialog is not None:
            dialog_patcher = patch("forms.import_runner.PeriodDialog", period_dialog)
            dialog_patcher.start()
            self.addCleanup(dialog_patcher.stop)

        runner = ImportRunner(paths, "airline", 1)
        self.addCleanup(runner.deleteLater)
        return runner

    def run_to_end(self, runner, timeout=15.0):
        """Крутит цикл событий, пока пакет не закончится."""
        outcome = {}
        runner.finished.connect(
            lambda results, cancelled: outcome.update(
                results=results, cancelled=cancelled
            )
        )
        runner.start()

        deadline = time.monotonic() + timeout
        while "results" not in outcome and time.monotonic() < deadline:
            QCoreApplication.processEvents(
                QEventLoop.ProcessEventsFlag.AllEvents, 10
            )
        self.assertIn("results", outcome, "импорт не завершился за отведённое время")
        return outcome


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ImportLeavesTheGuiThreadTest(ImportRunnerCase):
    """Разбор и запись выполняются не в потоке интерфейса."""

    def test_files_are_imported_off_the_gui_thread(self):
        stub = StubImport()
        runner = self.make_runner(["а.xlsx", "б.xlsx"], stub)

        self.run_to_end(runner)

        gui_thread = threading.current_thread()
        self.assertEqual(2, len(stub.threads))
        for worker_thread in stub.threads:
            self.assertIsNot(gui_thread, worker_thread)

    def test_window_keeps_repainting_while_the_import_runs(self):
        """Тот самый симптом: окно переставало отвечать на пачке файлов.

        Таймер — заместитель перерисовки: он обслуживается тем же циклом
        событий, который прежде был занят разбором книг.
        """
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        self.addCleanup(timer.stop)

        stub = StubImport(per_file_seconds=0.15)
        runner = self.make_runner(["а.xlsx", "б.xlsx", "в.xlsx"], stub)

        self.run_to_end(runner)

        self.assertEqual(3, len(stub.calls))
        self.assertGreater(len(ticks), 5)

    def test_worker_thread_is_stopped_when_the_batch_ends(self):
        stub = StubImport(per_file_seconds=0.01)
        runner = self.make_runner(["а.xlsx"], stub)
        stopped = []
        runner._thread.finished.connect(lambda: stopped.append(True))

        self.run_to_end(runner)

        self.assertEqual([True], stopped)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ImportReportsEveryFileTest(ImportRunnerCase):
    """Результат приходит по каждому файлу и в порядке загрузки."""

    def test_every_file_gets_its_own_result(self):
        stub = StubImport(per_file_seconds=0.01)
        runner = self.make_runner(["а.xlsx", "б.xlsx", "в.xlsx"], stub)

        outcome = self.run_to_end(runner)

        self.assertEqual(["а.xlsx", "б.xlsx", "в.xlsx"],
                         [r["source_file"] for r in outcome["results"]])
        self.assertFalse(outcome["cancelled"])

    def test_progress_counts_finished_files(self):
        stub = StubImport(per_file_seconds=0.01)
        runner = self.make_runner(["а.xlsx", "б.xlsx"], stub)
        # Значения снимаются по ходу: закрытый QProgressDialog сбрасывает своё в -1.
        values = []
        original = runner._progress.setValue
        runner._progress.setValue = lambda value: (values.append(value), original(value))[1]

        outcome = self.run_to_end(runner)

        self.assertEqual([0, 1, 2], values)
        self.assertEqual(2, len(outcome["results"]))
        self.assertEqual(2, runner._progress.maximum())

    def test_empty_selection_finishes_without_starting_a_thread(self):
        stub = StubImport()
        runner = self.make_runner([], stub)

        outcome = self.run_to_end(runner)

        self.assertEqual([], outcome["results"])
        self.assertEqual([], stub.calls)
        self.assertFalse(outcome["cancelled"])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ImportCanBeCancelledTest(ImportRunnerCase):
    """Отмена срабатывает между файлами — начатый файл дописывается.

    Прервать его на середине нельзя: импорт заменяет период целиком (DATA-5), и
    остановка на полпути оставила бы период наполовину переписанным.
    """

    def cancel_during_the_first_file(self, runner):
        """Нажимает «Отмена», пока первый файл ещё разбирается."""
        started = []

        def on_request(_request):
            if not started:
                started.append(True)
                # Кнопка «Отмена» соединена прямо с этим сигналом; вызов
                # `cancel()` его не испускает, а только прячет окно.
                QTimer.singleShot(0, runner._progress.canceled.emit)

        runner._request.connect(on_request)

    def test_remaining_files_are_not_started(self):
        stub = StubImport(per_file_seconds=0.15)
        runner = self.make_runner(["а.xlsx", "б.xlsx", "в.xlsx"], stub)
        self.cancel_during_the_first_file(runner)

        outcome = self.run_to_end(runner)

        self.assertEqual(1, len(stub.calls))
        self.assertTrue(outcome["cancelled"])

    def test_the_file_in_flight_is_finished_and_reported(self):
        stub = StubImport(per_file_seconds=0.15)
        runner = self.make_runner(["а.xlsx", "б.xlsx"], stub)
        self.cancel_during_the_first_file(runner)

        outcome = self.run_to_end(runner)

        self.assertEqual(1, len(outcome["results"]))
        self.assertEqual("а.xlsx", outcome["results"][0]["source_file"])
        self.assertTrue(outcome["results"][0]["success"])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class PeriodIsAskedInTheGuiThreadTest(ImportRunnerCase):
    """Файл без периода: вопрос задаётся, файл повторяется с ответом (DATA-2)."""

    def test_file_is_retried_with_the_answered_period(self):
        stub = StubImport(per_file_seconds=0.01, needs_period=["б.xlsx"])
        shown = []
        runner = self.make_runner(
            ["а.xlsx", "б.xlsx"], stub,
            period_dialog=fake_period_dialog(True, "March", 2026, shown),
        )

        outcome = self.run_to_end(runner)

        self.assertEqual(["б.xlsx"], shown)
        # Файл без периода разбирается дважды: вопрос задаётся по результату
        # первого разбора — определить период, не прочитав файл, нечем.
        self.assertEqual([("а.xlsx", None, None), ("б.xlsx", None, None),
                          ("б.xlsx", "March", 2026)], stub.calls)
        self.assertTrue(all(r["success"] for r in outcome["results"]))
        self.assertEqual(2, len(outcome["results"]))

    def test_declined_period_skips_the_file_and_keeps_the_batch(self):
        stub = StubImport(per_file_seconds=0.01, needs_period=["а.xlsx"])
        runner = self.make_runner(
            ["а.xlsx", "б.xlsx"], stub,
            period_dialog=fake_period_dialog(False),
        )

        outcome = self.run_to_end(runner)

        first, second = outcome["results"]
        self.assertFalse(first["success"])
        self.assertIn("период", first["message"].lower())
        self.assertTrue(second["success"])

    def test_period_is_asked_once_per_file(self):
        """Если и с указанным периодом разбор его не увидел, вопрос не повторяется.

        Иначе пакет зациклился бы на одном файле, а окно прогресса осталось бы
        на экране навсегда.
        """
        stub = StubImport(per_file_seconds=0.01)
        stub.needs_period = {"а.xlsx"}

        def always_needs_period(file_path, **kwargs):
            stub.calls.append((file_path, kwargs["month"], kwargs["year"]))
            return {
                "success": False,
                "period_required": True,
                "message": "период не определён",
                "source_file": os.path.basename(file_path),
            }

        shown = []
        runner = self.make_runner(
            ["а.xlsx"], always_needs_period,
            period_dialog=fake_period_dialog(True, "March", 2026, shown),
        )

        outcome = self.run_to_end(runner, timeout=5.0)

        self.assertEqual(1, len(shown))
        self.assertEqual(1, len(outcome["results"]))
        self.assertFalse(outcome["results"][0]["success"])


if __name__ == "__main__":
    unittest.main()
