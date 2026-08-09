"""аэропорт входит в предприятие

ФКП «Аэропорты Севера» сдаёт форму 15-ГА одним бланком на всё предприятие:
сводный блок самого ФКП и блок на каждый из его аэропортов. Сводный блок в
точности равен сумме своих аэропортов — проверено на присланном комплекте за
2025 год. Пока связи между ними в базе нет, свод по всем аэропортам складывает
и то и другое, и предприятие попадает в «Итого» дважды.

Ссылка ведёт на ту же таблицу, а не на отдельный справочник предприятий:
предприятие само сдаёт форму и имеет собственную отчётность, то есть во всём
остальном ведёт себя как аэропорт. Уровень при этом ровно один — разбивка
разбивки в форме не предусмотрена.

Колонка добавляется пустой: у существующих записей предприятие не угадывается
по названию, и проставить его должен человек — либо очередной импорт сводного
бланка, который знает состав предприятия из самого файла.

SQLite не умеет добавлять внешний ключ к готовой таблице, поэтому она
пересоздаётся batch-режимом. ON DELETE SET NULL, а не RESTRICT: потеря
группировки не должна мешать убрать ошибочно заведённую запись, а отчётность
к предприятию не привязана — она привязана к самому аэропорту.

Revision ID: a3e91d7c4b58
Revises: f1c3a7d90b26
Create Date: 2026-08-09 16:12:03.417925

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e91d7c4b58'
down_revision: Union[str, Sequence[str], None] = 'f1c3a7d90b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('airports') as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_airports_parent_id', 'airports', ['parent_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('airports') as batch_op:
        batch_op.drop_constraint('fk_airports_parent_id', type_='foreignkey')
        batch_op.drop_column('parent_id')
