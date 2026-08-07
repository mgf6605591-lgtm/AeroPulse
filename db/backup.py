# db/backup.py
"""Копия базы перед необратимыми операциями (FUNC-6).

В программе не было ни резервного копирования, ни отмены: диалог удаления честно
предупреждал, что действие необратимо, и это была вся защита. Отчётность при этом
приходит извне и восстанавливается только повторной загрузкой файлов, которые ещё
надо найти.

Копия снимается штатным механизмом SQLite (`Connection.backup`), а не копированием
файла: база работает в режиме WAL, и часть данных в момент копирования может лежать
в отдельном файле журнала — простое `shutil.copy` дало бы копию без них.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Сколько копий держать. Значение выбрано так, чтобы переживать серию правок за
# один день: копии снимаются перед каждой необратимой операцией, а не по времени.
KEEP_BACKUPS = 10

BACKUP_DIR_NAME = "backups"


def backup_dir(db_path: Path) -> Path:
    return db_path.parent / BACKUP_DIR_NAME


def backup_name(reason: str, moment: Optional[datetime] = None) -> str:
    """Имя копии: время и причина, по которой она снята."""
    moment = moment or datetime.now()
    safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in reason)
    return f"database-{moment:%Y%m%d-%H%M%S}-{safe_reason}.db"


def make_backup(db_path: Path, reason: str, keep: int = KEEP_BACKUPS) -> Optional[Path]:
    """Снимает копию базы и убирает лишние. Возвращает путь копии или None.

    Отсутствие базы — не ошибка: копировать нечего, а операция, ради которой
    копию снимали, должна продолжиться.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    target_dir = backup_dir(db_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / backup_name(reason)

    source = sqlite3.connect(str(db_path))
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    _rotate(target_dir, keep)
    return target


def existing_backups(db_path: Path) -> List[Path]:
    """Копии от новых к старым."""
    target_dir = backup_dir(Path(db_path))
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("database-*.db"), reverse=True)


def _rotate(target_dir: Path, keep: int) -> None:
    """Оставляет `keep` самых свежих копий.

    Ротация нужна не ради места: без неё каталог копий за месяц работы
    превращается в свалку, в которой нужную не найти.
    """
    backups = sorted(target_dir.glob("database-*.db"), reverse=True)
    for stale in backups[keep:]:
        stale.unlink(missing_ok=True)
