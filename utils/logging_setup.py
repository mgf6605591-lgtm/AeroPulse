# utils/logging_setup.py
"""Файловый журнал приложения (INFRA-2).

Диагностика велась через `print()` и `traceback.print_exc()`. В собранном
PyInstaller-ом окне стандартного вывода нет вовсе, поэтому всё это уходило в
никуда: расследовать проблему пользователя постфактум было нечем, а неудачный
запуск не оставлял и следа (BUG-15).

Туда же уходило то, что выводом называть нельзя, — отчёт миграции о том, сколько
дублирующих строк она удалила из пользовательских данных.

Файл лежит рядом с базой, в каталоге приложения: там же, где exe, и там же, где
пользователь уже ищет свои данные.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from utils.paths import get_app_dir

LOG_FILE_NAME = "aeropulse.log"

# Один файл на 2 МБ и три предыдущих: достаточно, чтобы застать позавчерашний
# запуск, и мало, чтобы не разрастаться незаметно.
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def log_path() -> Path:
    return get_app_dir() / LOG_FILE_NAME


def setup_logging(level: int = logging.INFO, path: Optional[Path] = None) -> Optional[Path]:
    """Настраивает журнал один раз за запуск. Возвращает путь файла или None.

    Невозможность писать журнал не должна мешать работать: у пользователя может
    не быть прав на запись рядом с exe (обычное дело для `C:\\Program Files`) —
    ровно тот случай, ради которого журнал и заводится. Тогда остаётся вывод в
    консоль, а приложение продолжает запускаться.
    """
    global _configured
    if _configured:
        return log_path()

    root = logging.getLogger()
    root.setLevel(level)

    target = Path(path) if path else log_path()
    written: Optional[Path] = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(file_handler)
        written = target
    except OSError:
        pass

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(stream_handler)

    _configured = True
    return written


def reset_for_tests() -> None:
    """Снимает настройку — тестам нужен чистый корневой журнал на каждый случай."""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    _configured = False
