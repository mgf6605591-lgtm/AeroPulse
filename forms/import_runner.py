# forms/import_runner.py
"""Пакетный импорт: рабочий поток, прогресс и отмена (BUG-11).

Цикл по выбранным файлам шёл прямо в обработчике нажатия, под курсором ожидания:
и разбор книги, и запись в базу — в потоке интерфейса. На пачке файлов окно
переставало перерисовываться, и Windows помечала его «Не отвечает».

Файлы обрабатываются по одному, а следующий шаг выбирает поток интерфейса — он
же показывает диалоги. Пока у пользователя спрашивают период, рабочий поток
простаивает. Ожидание на условной переменной сэкономило бы один разбор файла на
редком пути — и стоило бы мьютекса, разбудить который забывают ровно в той ветке,
которую не проверили.

**Отмена срабатывает между файлами.** Импорт заменяет период целиком (DATA-5), и
файл, прерванный на середине, оставил бы период наполовину переписанным — ту
самую потерю данных, ради которой заводились журнал (FUNC-5) и копия (FUNC-6).

Работа с базой из другого потока безопасна и без отдельных мер: движок открыт с
`NullPool` и `check_same_thread=False` ([db/database.py:25](db/database.py:25)),
поэтому соединение не переживает сессию и между потоками не переиспользуется.
"""
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QProgressDialog

from forms.widgets.period_dialog import PeriodDialog
from services.import_outcome import ImportOutcome, PeriodRequired, failure
from services.import_service import ImportService

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportRequest:
    """Один файл к загрузке. Период проставляется, только если его спросили."""

    file_path: str
    entity_type: str
    entity_id: int
    month: str | None = None
    year: int | None = None


class ImportWorker(QObject):
    """Разбор и запись одного файла. Живёт в рабочем потоке."""

    done = pyqtSignal(object, object)

    @pyqtSlot(object)
    def run_one(self, request: ImportRequest) -> None:
        try:
            result = ImportService.import_file(
                request.file_path,
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                month=request.month,
                year=request.year,
            )
        except Exception as error:
            # Исключение, выпущенное наружу, ушло бы в цикл событий рабочего
            # потока: пакет замер бы на этом файле, ничего не сообщив.
            log.exception("Импорт файла не выполнен: %s", request.file_path)
            result = failure(str(error), source_file=Path(request.file_path).name)
        self.done.emit(request, result)


class ImportRunner(QObject):
    """Ведёт пакет от первого файла до отчёта: поток, прогресс, вопрос о периоде.

    `finished` отдаёт результаты по каждому файлу в порядке загрузки и признак
    того, что пакет прерван пользователем.
    """

    finished = pyqtSignal(list, bool)
    _request = pyqtSignal(object)

    def __init__(self, paths, entity_type: str, entity_id: int, parent=None):
        super().__init__(parent)
        self._paths = list(paths)
        self._entity_type = entity_type
        self._entity_id = entity_id

        self._index = 0
        self._results: list[ImportOutcome] = []
        self._cancelled = False
        # Период спрашивается не более одного раза на файл: если и с указанным
        # периодом разбор его не увидел, повторять вопрос значило бы зациклиться.
        self._asked: set[str] = set()

        self._progress = QProgressDialog(
            "Подготовка…", "Отмена", 0, len(self._paths), parent
        )
        self._progress.setWindowTitle("Импорт файлов")
        # Модальность окна нужна не только ради порядка на экране: она же не даёт
        # закрыть главное окно посреди пакета, а с ним — увести из-под рабочего
        # потока и раннер, и сам `QThread`.
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        # Диалог закрывается вместе с концом пакета, а не сам по достижении
        # максимума: между последним файлом и отчётом ещё есть что показать.
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.canceled.connect(self._on_cancel)

        self._thread = QThread()
        self._worker = ImportWorker()
        self._worker.moveToThread(self._thread)
        self._worker.done.connect(self._on_file_done)
        self._request.connect(self._worker.run_one)
        self._thread.finished.connect(self._worker.deleteLater)

    def start(self) -> None:
        if not self._paths:
            self.finished.emit([], False)
            return
        self._thread.start()
        self._progress.setValue(0)
        self._send_next()

    # --- шаги пакета -------------------------------------------------------

    def _send_next(self) -> None:
        if self._cancelled or self._index >= len(self._paths):
            self._finish()
            return

        file_path = self._paths[self._index]
        self._progress.setLabelText(
            f"Файл {self._index + 1} из {len(self._paths)}: {Path(file_path).name}"
        )
        self._request.emit(
            ImportRequest(file_path, self._entity_type, self._entity_id)
        )

    def _on_file_done(self, request: ImportRequest, result: ImportOutcome) -> None:
        # Период не прочитался — спрашиваем его у пользователя вместо прежней
        # молчаливой подстановки «январь 2025» (DATA-2). Вопрос задаётся здесь,
        # в потоке интерфейса, пока рабочий поток свободен.
        if isinstance(result, PeriodRequired) and request.file_path not in self._asked:
            self._asked.add(request.file_path)
            retry = self._ask_period(request, result)
            if retry is not None:
                self._request.emit(retry)
                return
            result = failure(
                "Файл пропущен: отчётный период не указан.",
                source_file=Path(request.file_path).name,
            )

        self._results.append(result)
        self._index += 1
        self._progress.setValue(self._index)
        self._send_next()

    def _ask_period(self, request: ImportRequest, result: PeriodRequired) -> ImportRequest | None:
        """Спрашивает период. None — файл пропускается."""
        dialog = PeriodDialog(
            Path(request.file_path).name,
            month=result.month,
            year=result.year,
            parent=self._progress.parent() or self._progress,
        )
        if dialog.exec() != PeriodDialog.DialogCode.Accepted:
            return None
        return replace(request, month=dialog.get_month(), year=dialog.get_year())

    def _on_cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        # Текущий файл дописывается до конца, и об этом нужно сказать: иначе
        # между нажатием «Отмена» и закрытием окна ничего не происходит.
        # `QProgressDialog` по нажатию прячет себя сам — возвращаем его.
        self._progress.setLabelText("Отмена: дожидаемся конца текущего файла…")
        self._progress.show()

    def _finish(self) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread.deleteLater()
        # Отписаться нужно до закрытия: `QProgressDialog` испускает `canceled` не
        # только по кнопке, но и из `closeEvent`, — иначе пакет, дошедший до
        # последнего файла, отмечался бы прерванным в самый момент закрытия окна.
        self._progress.canceled.disconnect(self._on_cancel)
        self._progress.close()
        self.finished.emit(self._results, self._cancelled)
