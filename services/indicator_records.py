# services/indicator_records.py
"""Общее у правки и удаления отчётной строки: какая таблица и копия базы.

Оба действия начинаются одинаково — назвать по виду отчётности таблицу, снять
копию базы и не трогать данные, если копия не снялась (FUNC-13). Правило это
писалось для удаления и жило в `services/deletion_service.py`; правке оно нужно
слово в слово, а скопированный блок расходится с оригиналом молча — так в первом
реестре и появился BUG-1.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from db.backup import make_backup
from db.database import db_path
from db.models.entities import AirlineIndicators, AirportIndicators

log = logging.getLogger(__name__)


class BackupUnavailable(RuntimeError):
    """Копию базы снять не удалось, а изменение её не дождалось (FUNC-13).

    Отдельное исключение, а не общий отказ: оно означает не «не вышло», а «ещё
    не пробовали». Копия снимается **до** изменения, поэтому в этот момент ещё
    ничего не потеряно и решение можно оставить пользователю — для этого у
    служб есть `require_backup=False`.
    """


@dataclass(frozen=True)
class IndicatorTable:
    """Таблица отчётных строк и поле, которым строка привязана к предприятию.

    Поле разное не по прихоти: у 12-ГА строка висит на рейсе (авиакомпания плюс
    маршрут), у 15-ГА — прямо на аэропорте. Ключ отчётной строки в обоих случаях
    один и тот же по смыслу: показатель, предприятие, месяц, год.
    """

    model: type
    owner_field: str


# Вид отчётности → таблица. Словарь, а не пара веток `if`: неизвестный вид
# должен быть отказом, а не молчаливым попаданием в аэропорты.
_TABLES = {
    "airline": IndicatorTable(AirlineIndicators, "shipping_id"),
    "airport": IndicatorTable(AirportIndicators, "airport_id"),
}


def table_for(entity_type: str) -> IndicatorTable:
    """Таблица отчётности по её виду. Неизвестный вид — `ValueError`."""
    table = _TABLES.get(entity_type)
    if table is None:
        raise ValueError(f"Неизвестный вид отчётности: {entity_type!r}")
    return table


def guarded_backup(*, require_backup: bool, reason: str) -> Path | None:
    """Копия базы перед изменением.

    None означает «копировать было нечего»: файла базы нет — `make_backup`
    сообщает об этом возвратом, а не исключением, и менять там тоже нечего.
    Настоящая неудача — исключение, и она либо останавливает изменение, либо
    прощена вызывающим; в журнал приложения она попадает в обоих случаях.
    """
    try:
        return make_backup(db_path(), reason=reason)
    except Exception as error:
        log.exception("Не удалось снять копию базы")
        if require_backup:
            raise BackupUnavailable(str(error)) from error
        return None
