# services/edit_service.py
"""Правка отчётной строки: копия базы, изменение, запись в журнал (ARCH-16).

Правят три поля — значение, месяц и год. Остальное строку определяет: показатель,
предприятие и (у 12-ГА) рейс — это не свойства записи, а то, чем она является;
сменить их значит завести другую строку, а не исправить эту.

Порядок тот же, что и при удалении: сначала копия базы, потом изменение, потом
журнал. Прежнего значения после записи не остаётся нигде, кроме копии и журнала,
— поэтому в журнал уходит и то, что было, и то, что стало (FUNC-5).

Об ошибке служба сообщает исключением, а не значением: показать её — дело
вызывающего, и в отличие от окна у него может не быть экрана (ARCH-2).
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from db.database import get_session
from db.models.enums import Months
from services import journal_service as journal
from services.indicator_records import BackupUnavailable, guarded_backup, table_for

log = logging.getLogger(__name__)

__all__ = [
    "BackupUnavailable",
    "EditResult",
    "PeriodTaken",
    "RecordGone",
    "update_indicator",
]


class RecordGone(LookupError):
    """Строки с таким id больше нет: её удалили, пока окно её показывало."""


class PeriodTaken(RuntimeError):
    """За новый период такая строка уже есть.

    Ключ отчётной строки — показатель, предприятие, месяц и год: две строки на
    один период база не примет. Без этой проверки правка периода падала бы
    нарушением уникального индекса — сообщением SQLite поверх русского окна.
    """


@dataclass(frozen=True)
class EditResult:
    """Что произошло: изменилась ли строка и куда легла копия базы.

    `changed` — False, когда в диалоге ничего не поменяли и нажали «Сохранить»:
    записывать нечего, и в журнал такая правка не идёт.
    """

    changed: bool
    backup: Path | None


def update_indicator(
    entity_type: str, record_id: int, *,
    month: Months, year: int, value: Decimal,
    user: str | None = None, require_backup: bool = True
) -> EditResult:
    """Меняет значение и период отчётной строки, сняв перед этим копию базы.

    Копия обязательна: не снялась — `BackupUnavailable`, и в базе ничего не
    менялось. `require_backup=False` снимает это требование, но только явно и
    только от того, кто спросил у человека, — как и при удалении (FUNC-13).
    """
    table = table_for(entity_type)

    # Сначала читаем, и только потом снимаем копию: копия — это файл базы на
    # диск, и снимать её, чтобы затем выяснить, что менять нечего или что период
    # занят, незачем. Правило «копия до изменения» это не нарушает — до
    # изменения, а не до чтения.
    with get_session() as session:
        record = _record(session, table, record_id)
        changes = _describe_changes(record, month=month, year=year, value=value)
        if not changes:
            return EditResult(changed=False, backup=None)
        _refuse_taken_period(session, table, record, month=month, year=year)

    backup_path = guarded_backup(require_backup=require_backup, reason="edit")

    with get_session() as session:
        record = _record(session, table, record_id)
        record.month = month
        record.year = year
        record.value = value

        journal.record_safely(
            session,
            kind=journal.KIND_REPLACE,
            entity_type=entity_type,
            month=month,
            year=year,
            updated=1,
            # Номер строки — в сообщение, а не в `entity_id`: там журнал держит
            # предприятие, и запись отчётности на его месте читалась бы как чужая.
            message=f"запись {record_id}: " + "; ".join(changes),
            user=user,
        )
        session.commit()

    return EditResult(changed=True, backup=backup_path)


def _record(session, table, record_id: int):
    """Строка отчётности из открытой сессии; её отсутствие — не «ничего»."""
    record = session.get(table.model, record_id)
    if record is None:
        raise RecordGone(f"Запись {record_id} не найдена")
    return record


def _describe_changes(record, *, month: Months, year: int, value: Decimal) -> list[str]:
    """Что именно меняется — словами, для журнала.

    Сравнение заодно отвечает на вопрос, меняется ли хоть что-нибудь: правка,
    в которой ничего не тронули, не должна ни писаться в журнал, ни выглядеть
    как изменение отчётности.
    """
    changes = []
    if record.value != value:
        changes.append(f"значение: {record.value} → {value}")
    if record.month != month or record.year != year:
        changes.append(f"период: {_period(record.month, record.year)} → {_period(month, year)}")
    return changes


def _period(month: Months | None, year: int | None) -> str:
    """«Январь 2025» — подпись месяца берётся у самого перечисления."""
    return f"{month.value if month else '—'} {year}"


def _refuse_taken_period(session, table, record, *, month: Months, year: int) -> None:
    """Отказ, если за новый период такая же строка уже заведена."""
    if record.month == month and record.year == year:
        return

    owner_id = getattr(record, table.owner_field)
    taken = (
        session.query(table.model)
        .filter(
            table.model.indicator_id == record.indicator_id,
            getattr(table.model, table.owner_field) == owner_id,
            table.model.month == month,
            table.model.year == year,
        )
        .first()
    )
    if taken is not None and taken.id != record.id:
        raise PeriodTaken(
            f"За {_period(month, year)} такая запись уже есть (id {taken.id})."
        )
