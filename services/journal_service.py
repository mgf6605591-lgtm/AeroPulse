# services/journal_service.py
"""Запись в журнал загрузок и удалений (FUNC-5).

Журнал пишется в той же транзакции, что и само изменение: иначе он рассказывал бы
о том, чего не случилось, — или молчал о том, что случилось.

Ошибка записи в журнал не отменяет операцию и не показывается пользователю:
журнал важен, но не важнее того, ради чего пользователь пришёл. Зато и молча она
не теряется — сообщение уходит в тот же вывод, что и остальные (INFRA-2 ещё
открыт: файлового журнала у приложения пока нет).
"""
import traceback
from typing import Optional

from db.database import get_session
from db.models.entities import ImportLog

KIND_IMPORT = "import"
KIND_DELETE = "delete"
KIND_REPLACE = "replace"


def record(session, *, kind: str, source_file: Optional[str] = None,
           entity_type: Optional[str] = None, entity_id: Optional[int] = None,
           entity_name: Optional[str] = None, month=None, year: Optional[int] = None,
           imported: int = 0, updated: int = 0, removed: int = 0,
           message: Optional[str] = None, user: Optional[str] = None) -> None:
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
        print("Не удалось записать строку журнала:")
        traceback.print_exc()


def record_deletion(*, count: int, entity_type: Optional[str] = None,
                    message: Optional[str] = None, user: Optional[str] = None) -> None:
    """Отдельная запись об удалении — в своей сессии, после самого удаления."""
    try:
        with get_session() as session:
            record(session, kind=KIND_DELETE, entity_type=entity_type,
                   removed=count, message=message, user=user)
            session.commit()
    except Exception:
        print("Не удалось записать удаление в журнал:")
        traceback.print_exc()


def _file_name(path: Optional[str]) -> Optional[str]:
    """В журнал идёт имя файла, а не полный путь: путь к чужому каталогу ничего
    не добавляет к прослеживаемости, зато попадает в базу вместе с ним."""
    if not path:
        return None
    return path.replace("\\", "/").rsplit("/", 1)[-1][:255]
