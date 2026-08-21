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
from collections.abc import Sequence

from db.database import get_session
from services import journal_service as journal
from services.indicator_records import BackupUnavailable, guarded_backup, table_for

log = logging.getLogger(__name__)

# Имя оставлено импортируемым отсюда: удаление — главный повод для отказа из-за
# копии, и вызывающие ловят его рядом с `delete_indicators`.
__all__ = ["BackupUnavailable", "DeletionResult", "delete_indicators"]


@dataclass(frozen=True)
class DeletionResult:
    """Что произошло: сколько строк удалено и куда легла копия базы.

    `backup` — None, когда копировать было нечего: файла базы нет, а значит нет
    и того, что копия защищала бы. Неудача копирования сюда не попадает — она
    поднимается `BackupUnavailable` и требует явного решения.
    """

    deleted: int
    backup: Path | None


def delete_indicators(
    entity_type: str, ids: Sequence[int], *,
    user: str | None = None, require_backup: bool = True
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
    model = table_for(entity_type).model
    backup_path = guarded_backup(require_backup=require_backup, reason="delete")

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
