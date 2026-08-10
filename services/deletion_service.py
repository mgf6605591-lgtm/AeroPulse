# services/deletion_service.py
"""Удаление отчётности: копия базы, само удаление, запись в журнал (ARCH-16).

Порядок этих трёх шагов — правило работы с отчётностью, а не подробность окна:
отменить удаление нечем, и восстанавливается оно только повторной загрузкой
файлов, которые ещё надо найти (FUNC-6), а по журналу потом видно, что и когда
пропало (FUNC-5).

Жило правило в слоте Qt — в `MainWindow.delete_records`. Позвать его вторым
способом (из окна справочников, из будущего «удалить период целиком») можно было
только переписав все три шага заново, а проверить без экрана — никак. Первый
реестр показывает, чем такое кончается: BUG-1 — блок, скопированный вместе с
ошибкой, ARCH-8…ARCH-11 — семь мест дублирования.

Рядом, в том же окне, импорт устроен уже правильно: окно спрашивает и показывает
итог, а копию, запись и журнал ведут `ImportService` и `DataImporter`.

Об ошибке служба сообщает исключением, а не значением: показать её — дело
вызывающего, и в отличие от окна у него может не быть экрана (ARCH-2).
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from db.backup import make_backup
from db.database import db_path, get_session
from db.models.entities import AirlineIndicators, AirportIndicators
from services import journal_service as journal

log = logging.getLogger(__name__)

# Вид отчётности → таблица, из которой удаляют. Словарь, а не пара веток `if`:
# неизвестный вид должен быть отказом, а не молчаливым попаданием в аэропорты.
_MODEL_BY_ENTITY = {
    "airline": AirlineIndicators,
    "airport": AirportIndicators,
}


class BackupUnavailable(RuntimeError):
    """Копию базы снять не удалось, а удаление её не дождалось (FUNC-13).

    Отдельное исключение, а не общий отказ: оно означает не «удалить не вышло»,
    а «удалить пока не пробовали». Копия снимается **до** удаления, поэтому в
    этот момент ещё ничего не потеряно и решение можно оставить пользователю —
    для этого у `delete_indicators` есть `require_backup=False`.
    """


@dataclass(frozen=True)
class DeletionResult:
    """Что произошло: сколько строк удалено и куда легла копия базы.

    `backup` — None, когда копировать было нечего: файла базы нет, а значит нет
    и того, что копия защищала бы. Неудача копирования сюда не попадает — она
    поднимается `BackupUnavailable` и требует явного решения.
    """

    deleted: int
    backup: Optional[Path]


def delete_indicators(
    entity_type: str, ids: Sequence[int], *,
    user: Optional[str] = None, require_backup: bool = True
) -> DeletionResult:
    """Удаляет строки отчётности, сняв перед этим копию базы и записав журнал.

    Отсутствующий id пропускается молча: строку могли удалить в другом окне,
    и падать на этом незачем — в результат попадёт число реально удалённых.

    Копия обязательна: не снялась — `BackupUnavailable`, и в базе ничего не
    менялось. `require_backup=False` снимает это требование, но только явно и
    только от того, кто спросил у человека. Прежде неудача копирования просто
    писалась в журнал приложения, а удаление шло дальше — и «Готово» выглядело
    так же, как с копией (FUNC-13).
    """
    model = _MODEL_BY_ENTITY.get(entity_type)
    if model is None:
        raise ValueError(f"Неизвестный вид отчётности: {entity_type!r}")

    backup_path = _make_backup(require_backup)

    deleted = 0
    with get_session() as session:
        for record_id in ids:
            record = session.get(model, record_id)
            if record is not None:
                session.delete(record)
                deleted += 1
        session.commit()

    journal.record_deletion(
        count=deleted,
        entity_type=entity_type,
        message=(
            f"копия базы: {backup_path.name}" if backup_path else "копия базы не снята"
        ),
        user=user,
    )
    return DeletionResult(deleted=deleted, backup=backup_path)


def _make_backup(require_backup: bool) -> Optional[Path]:
    """Копия базы перед удалением.

    None означает «копировать было нечего»: файла базы нет — `make_backup`
    сообщает об этом возвратом, а не исключением, и удалять там тоже нечего.
    Настоящая неудача — исключение, и она либо останавливает удаление, либо
    прощена вызывающим; в журнал приложения она попадает в обоих случаях.
    """
    try:
        return make_backup(db_path(), reason="delete")
    except Exception as error:
        log.exception("Не удалось снять копию базы")
        if require_backup:
            raise BackupUnavailable(str(error)) from error
        return None
