"""длины текстовых полей по реальным данным

Объявленные лимиты отчётность не вмещали (SCH-6). Разбор 15-ГА складывает
название показателя из названия строки бланка и названия графы, и самое длинное
из того, что он порождает, — «Коммерческие перевозки - всего (стр.03+стр.07) —
Пассажиры всего (гр.4+гр.5), чел.» — занимает 82 символа при объявленных
пятидесяти. Код той же формы, «15ГА-R04ИНО-ПАС_ВСЕГО», — 21 при двадцати. Оба
значения не оценочные: столько лежит в рабочей базе прямо сейчас.

SQLite длину VARCHAR не проверяет, поэтому расхождение ничем себя не выдавало и
данные не терялись. На PostgreSQL или MSSQL импорт 15-ГА упал бы на первой же
строке — а перенос на другую СУБД тем и опасен, что схема выглядит рабочей.

Тип колонки на SQLite меняется пересозданием таблицы (`batch_alter_table`).
Уникальные ограничения здесь безымянные, а внешние ключи несут ON DELETE, от
которых зависит целостность (SCH-2, SCH-5, SCH-10): и то и другое переносится
отражением исходной таблицы, и что перенеслось — проверяют `tests/test_schema.py`
и сверка метаданных в `tests/test_migrations.py`.

Обратный переход оставлен для полноты линии. На строгой СУБД он может не пройти:
названия длиннее пятидесяти символов в старый лимит не помещаются — собственно,
поэтому его и меняем.

Revision ID: f1c3a7d90b26
Revises: e2b8f30d1a47
Create Date: 2026-08-08 11:20:41.663214

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c3a7d90b26'
down_revision: Union[str, Sequence[str], None] = 'e2b8f30d1a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# таблица -> ((колонка, было, стало, nullable), …)
WIDENED = {
    "users": (("email", 25, 320, False),),
    "airports": (("name", 25, 255, False),),
    "airport_localities": (("name", 50, 255, False),),
    "airlines": (("name", 50, 255, False),),
    "indicators": (("name", 50, 255, False), ("code", 20, 64, False)),
    "import_log": (("entity_name", 100, 255, True),),
}


def _resize(*, to_new: bool) -> None:
    for table, columns in WIDENED.items():
        # Одна перестройка на таблицу: у indicators меняются две колонки сразу.
        with op.batch_alter_table(table) as batch:
            for column, old, new, nullable in columns:
                source, target = (old, new) if to_new else (new, old)
                batch.alter_column(
                    column,
                    existing_type=sa.String(length=source),
                    type_=sa.String(length=target),
                    existing_nullable=nullable,
                )


def upgrade() -> None:
    _resize(to_new=True)


def downgrade() -> None:
    _resize(to_new=False)
