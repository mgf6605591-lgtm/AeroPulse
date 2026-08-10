# services/journal_service.py
"""Запись в журнал загрузок и удалений (FUNC-5).

Журнал пишется в той же транзакции, что и само изменение: иначе он рассказывал бы
о том, чего не случилось, — или молчал о том, что случилось.

Ошибка записи в журнал не отменяет операцию и не показывается пользователю:
журнал важен, но не важнее того, ради чего пользователь пришёл. Зато и молча она
не теряется — уходит в файловый журнал приложения.
"""
import logging

from db.database import get_session
from db.models.entities import ImportLog

log = logging.getLogger(__name__)

KIND_IMPORT = "import"
KIND_DELETE = "delete"
KIND_REPLACE = "replace"


def record(session, *, kind: str, source_file: str | None = None,
           entity_type: str | None = None, entity_id: int | None = None,
           entity_name: str | None = None, month=None, year: int | None = None,
           imported: int = 0, updated: int = 0, removed: int = 0,
           message: str | None = None, user: str | None = None) -> None:
    """Добавляет строку журнала в открытую сессию (без commit)."""
    session.add(ImportLog(
        kind=kind,
        source_file=_file_name(source_file),
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        month=month,
        year=year,
        imported=imported,
        updated=updated,
        removed=removed,
        message=(message or "")[:500] or None,
        user=user,
    ))


def record_safely(session, **fields) -> None:
    """То же, но неудача записи не срывает операцию."""
    try:
        record(session, **fields)
    except Exception:
        log.exception("Не удалось записать строку журнала")


def record_deletion(*, count: int, entity_type: str | None = None,
                    message: str | None = None, user: str | None = None) -> None:
    """Отдельная запись об удалении — в своей сессии, после самого удаления."""
    try:
        with get_session() as session:
            record(session, kind=KIND_DELETE, entity_type=entity_type,
                   removed=count, message=message, user=user)
            session.commit()
    except Exception:
        log.exception("Не удалось записать удаление в журнал")


def _file_name(path: str | None) -> str | None:
    """В журнал идёт имя файла, а не полный путь: путь к чужому каталогу ничего
    не добавляет к прослеживаемости, зато попадает в базу вместе с ним."""
    if not path:
        return None
    return path.replace("\\", "/").rsplit("/", 1)[-1][:255]
