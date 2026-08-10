"""ведение справочников: флаг активности и запрет удаления предприятий с отчётностью

Закрывает SCH-10. Пока форм ведения справочников не было (FUNC-1), удалять их строки
было нечем, и опасность оставалась латентной: удаление аэропорта или авиакомпании
каскадом стирало всю их отчётность за все периоды, а резервных копий и журнала
удалений в проекте нет.

Вместо одного каскада — два разных сценария:

  «ошибочно заведена»  — запись без отчётности удаляется как раньше;
  «выведена из работы» — запись с отчётностью удалить нельзя (RESTRICT), её помечают
                         неактивной: история сохраняется, из списков выбора уходит.

FK у SQLite нельзя изменить на месте, поэтому таблицы пересоздаются batch-режимом.
copy_from здесь не нужен: ограничения получили имена в ревизии 1d93677c2cb4, поэтому
адресуются по отражённой схеме.

Revision ID: 6fd62d1c1c87
Revises: 1d93677c2cb4
Create Date: 2026-08-06 23:26:29.985482

"""
from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fd62d1c1c87'
down_revision: str | Sequence[str] | None = '1d93677c2cb4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Существующие записи считаются действующими: понятия «недействующая» до этой
    # ревизии не было, и справочники заполнялись рабочими данными.
    op.add_column('airports', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('airlines', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))

    with op.batch_alter_table('airportInd') as batch_op:
        batch_op.drop_constraint('fk_airportInd_airport_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_airportInd_airport_id', 'airports', ['airport_id'], ['id'], ondelete='RESTRICT'
        )

    # Запрет ставится на рейсы, а не на сами отчётные строки: рейс создаётся импортом,
    # поэтому его наличие и означает, что у предприятия есть накопленные данные.
    with op.batch_alter_table('shipping') as batch_op:
        batch_op.drop_constraint('fk_shipping_airline_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_shipping_airline_id', 'airlines', ['airline_id'], ['id'], ondelete='RESTRICT'
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('shipping') as batch_op:
        batch_op.drop_constraint('fk_shipping_airline_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_shipping_airline_id', 'airlines', ['airline_id'], ['id'], ondelete='CASCADE'
        )

    with op.batch_alter_table('airportInd') as batch_op:
        batch_op.drop_constraint('fk_airportInd_airport_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_airportInd_airport_id', 'airports', ['airport_id'], ['id'], ondelete='CASCADE'
        )

    op.drop_column('airlines', 'is_active')
    op.drop_column('airports', 'is_active')
