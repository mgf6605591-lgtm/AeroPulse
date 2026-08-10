"""значения отчётности хранятся точно, а не двоичным float

Закрывает потерю точности при записи (BUG-4). Колонка `value` была объявлена как
`DECIMAL`, но у этого типа в SQLite числовое сродство: значение ложилось как
`REAL`, то есть двоичное приближение десятичного числа из бланка. Импортёр вдобавок
сам приводил `Decimal` к `float` перед записью.

Ревизия переводит обе колонки значений в текст (`VARCHAR`) — тип с текстовым
сродством, из которого `Decimal` читается ровно тем же, каким записан. Уже
накопленные значения переносятся приведением `CAST(value AS TEXT)`: SQLite отдаёт
кратчайшую запись, дающую тот же `REAL`, поэтому «140.62» останется «140.62», а не
превратится в «140.62000000000000454747350886464118957519531250».

Точность прошлых импортов ревизия не восстанавливает — восстанавливать её не из
чего: исходные десятичные знаки потеряны при записи. Она лишь прекращает потерю
на будущее и фиксирует то, что уже лежит в базе.

Revision ID: c8f1b4d27a63
Revises: b7a4c9f21e05
Create Date: 2026-08-07 14:02:18.551204

"""
from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f1b4d27a63'
down_revision: str | Sequence[str] | None = 'b7a4c9f21e05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALUE_TABLES = ('airlineInd', 'airportInd')


def upgrade() -> None:
    # batch_alter_table пересоздаёт таблицу и переливает данные: в SQLite тип
    # колонки иначе не меняется. Перелив идёт через INSERT ... SELECT, поэтому
    # сродство новой колонки само превращает REAL в текст.
    for table in VALUE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                'value',
                existing_type=sa.DECIMAL(),
                type_=sa.String(),
                existing_nullable=False,
            )


def downgrade() -> None:
    # Обратный переход снова кладёт значения в REAL, то есть снова теряет точность:
    # это и есть состояние до ревизии.
    for table in VALUE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                'value',
                existing_type=sa.String(),
                type_=sa.DECIMAL(),
                existing_nullable=False,
            )
