"""уникальные ключи отчётных строк и рабочие правила ON DELETE

Закрывает SCH-3 (дедупликация возложена на прикладной код), SCH-4 (удаление рейса
оставляло висячие показатели) и SCH-5 (удаление населённого пункта стирало аэропорты
вместе с отчётностью).

FK у SQLite нельзя изменить на месте, поэтому таблицы пересоздаются batch-режимом.
copy_from задаёт исходное определение таблицы: в базе ограничения безымянные, и без
явных имён их нельзя адресовать в drop_constraint.

Перед созданием уникальных ключей накопленные дубли схлопываются: в фактовых
таблицах выигрывает последняя загруженная строка (MAX(id)) — так же, как при
повторном импорте отчёта; в справочных остаётся первая (MIN(id)), а ссылки на
удаляемые строки переводятся на неё.

Revision ID: 1d93677c2cb4
Revises: 9d180a1255ac
Create Date: 2026-08-06 20:24:11.038217

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d93677c2cb4'
down_revision: Union[str, Sequence[str], None] = '9d180a1255ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MONTHS = sa.Enum(
    'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December', name='months',
)


def _old_airline_ind() -> sa.Table:
    return sa.Table(
        'airlineInd', sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('indicator_id', sa.Integer(), nullable=False),
        sa.Column('shipping_id', sa.Integer(), nullable=False),
        sa.Column('month', _MONTHS, nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('value', sa.DECIMAL(), nullable=False),
        sa.ForeignKeyConstraint(['indicator_id'], ['indicators.id'], name='fk_airlineInd_indicator_id'),
        sa.ForeignKeyConstraint(['shipping_id'], ['shipping.id'], name='fk_airlineInd_shipping_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id'),
    )


def _old_airport_ind() -> sa.Table:
    return sa.Table(
        'airportInd', sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('indicator_id', sa.Integer(), nullable=False),
        sa.Column('airport_id', sa.Integer(), nullable=False),
        sa.Column('month', _MONTHS, nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('value', sa.DECIMAL(), nullable=False),
        sa.ForeignKeyConstraint(['airport_id'], ['airports.id'], name='fk_airportInd_airport_id'),
        sa.ForeignKeyConstraint(['indicator_id'], ['indicators.id'], name='fk_airportInd_indicator_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id'),
    )


def _old_airports() -> sa.Table:
    return sa.Table(
        'airports', sa.MetaData(),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=5), nullable=False),
        sa.Column('name', sa.String(length=25), nullable=False),
        sa.Column('locality_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['locality_id'], ['airport_localities.id'], name='fk_airports_locality_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )


def _old_indicators() -> sa.Table:
    return sa.Table(
        'indicators', sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('measure', sa.String(length=20), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['indicators.id'], name='fk_indicators_parent_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('id'),
    )


def _old_shipping() -> sa.Table:
    return sa.Table(
        'shipping', sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('route_id', sa.Integer(), nullable=False),
        sa.Column('airline_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['airline_id'], ['airlines.id'], name='fk_shipping_airline_id'),
        sa.ForeignKeyConstraint(['route_id'], ['routes.id'], name='fk_shipping_route_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id'),
    )


def _collapse_duplicates() -> None:
    """Схлопывает дубли, накопленные до появления уникальных ключей."""
    conn = op.get_bind()

    # Справочники: ссылки переводятся на первую строку пары, остальные удаляются.
    conn.exec_driver_sql("""
        UPDATE shipping SET route_id = (
            SELECT MIN(r.id) FROM routes r
            WHERE r.type = (SELECT type FROM routes WHERE id = shipping.route_id)
              AND r.regularity = (SELECT regularity FROM routes WHERE id = shipping.route_id)
        )
    """)
    routes = conn.exec_driver_sql(
        "DELETE FROM routes WHERE id NOT IN (SELECT MIN(id) FROM routes GROUP BY type, regularity)"
    ).rowcount

    conn.exec_driver_sql("""
        UPDATE airlineInd SET shipping_id = (
            SELECT MIN(s.id) FROM shipping s
            WHERE s.airline_id = (SELECT airline_id FROM shipping WHERE id = airlineInd.shipping_id)
              AND s.route_id = (SELECT route_id FROM shipping WHERE id = airlineInd.shipping_id)
        )
    """)
    shipping = conn.exec_driver_sql(
        "DELETE FROM shipping WHERE id NOT IN (SELECT MIN(id) FROM shipping GROUP BY airline_id, route_id)"
    ).rowcount

    # Отчётные строки: после перевода ссылок дубли могли появиться заново,
    # поэтому чистим их последними. Выигрывает последняя загруженная строка.
    airline_ind = conn.exec_driver_sql("""
        DELETE FROM airlineInd WHERE id NOT IN (
            SELECT MAX(id) FROM airlineInd GROUP BY indicator_id, shipping_id, month, year
        )
    """).rowcount
    airport_ind = conn.exec_driver_sql("""
        DELETE FROM airportInd WHERE id NOT IN (
            SELECT MAX(id) FROM airportInd GROUP BY indicator_id, airport_id, month, year
        )
    """).rowcount

    removed = {
        'routes': routes,
        'shipping': shipping,
        'airlineInd': airline_ind,
        'airportInd': airport_ind,
    }
    if any(removed.values()):
        # Это отчёт об изменении пользовательских данных, а не диагностика:
        # операция необратима и однократна, а в собранном окне stdout нет —
        # сообщение о ней не должно теряться (INFRA-2).
        logging.getLogger(__name__).warning(
            "Миграция %s: удалены дубликаты — %s", revision, removed
        )


def upgrade() -> None:
    """Upgrade schema."""
    _collapse_duplicates()

    with op.batch_alter_table('airlineInd', copy_from=_old_airline_ind()) as batch_op:
        batch_op.drop_constraint('fk_airlineInd_indicator_id', type_='foreignkey')
        batch_op.drop_constraint('fk_airlineInd_shipping_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_airlineInd_indicator_id', 'indicators', ['indicator_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_foreign_key('fk_airlineInd_shipping_id', 'shipping', ['shipping_id'], ['id'], ondelete='CASCADE')
        batch_op.create_index('uq_airline_ind_period', ['indicator_id', 'shipping_id', 'month', 'year'], unique=True)

    with op.batch_alter_table('airportInd', copy_from=_old_airport_ind()) as batch_op:
        batch_op.drop_constraint('fk_airportInd_airport_id', type_='foreignkey')
        batch_op.drop_constraint('fk_airportInd_indicator_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_airportInd_indicator_id', 'indicators', ['indicator_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_foreign_key('fk_airportInd_airport_id', 'airports', ['airport_id'], ['id'], ondelete='CASCADE')
        batch_op.create_index('uq_airport_ind_period', ['indicator_id', 'airport_id', 'month', 'year'], unique=True)

    with op.batch_alter_table('airports', copy_from=_old_airports()) as batch_op:
        batch_op.drop_constraint('fk_airports_locality_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_airports_locality_id', 'airport_localities', ['locality_id'], ['id'], ondelete='RESTRICT')

    with op.batch_alter_table('indicators', copy_from=_old_indicators()) as batch_op:
        batch_op.drop_constraint('fk_indicators_parent_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_indicators_parent_id', 'indicators', ['parent_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('shipping', copy_from=_old_shipping()) as batch_op:
        batch_op.drop_constraint('fk_shipping_airline_id', type_='foreignkey')
        batch_op.drop_constraint('fk_shipping_route_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_shipping_airline_id', 'airlines', ['airline_id'], ['id'], ondelete='CASCADE')
        batch_op.create_foreign_key('fk_shipping_route_id', 'routes', ['route_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_index('uq_shipping_airline_route', ['airline_id', 'route_id'], unique=True)

    with op.batch_alter_table('routes', schema=None) as batch_op:
        batch_op.create_index('uq_routes_type_regularity', ['type', 'regularity'], unique=True)


def downgrade() -> None:
    """Downgrade schema.

    Возвращает FK без ON DELETE и снимает уникальные ключи; удалённые дубликаты
    не восстанавливаются.
    """
    with op.batch_alter_table('routes', schema=None) as batch_op:
        batch_op.drop_index('uq_routes_type_regularity')

    with op.batch_alter_table('shipping', schema=None) as batch_op:
        batch_op.drop_index('uq_shipping_airline_route')
        batch_op.drop_constraint('fk_shipping_airline_id', type_='foreignkey')
        batch_op.drop_constraint('fk_shipping_route_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_shipping_airline_id', 'airlines', ['airline_id'], ['id'])
        batch_op.create_foreign_key('fk_shipping_route_id', 'routes', ['route_id'], ['id'])

    with op.batch_alter_table('indicators', schema=None) as batch_op:
        batch_op.drop_constraint('fk_indicators_parent_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_indicators_parent_id', 'indicators', ['parent_id'], ['id'])

    with op.batch_alter_table('airports', schema=None) as batch_op:
        batch_op.drop_constraint('fk_airports_locality_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_airports_locality_id', 'airport_localities', ['locality_id'], ['id'])

    with op.batch_alter_table('airportInd', schema=None) as batch_op:
        batch_op.drop_index('uq_airport_ind_period')
        batch_op.drop_constraint('fk_airportInd_airport_id', type_='foreignkey')
        batch_op.drop_constraint('fk_airportInd_indicator_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_airportInd_indicator_id', 'indicators', ['indicator_id'], ['id'])
        batch_op.create_foreign_key('fk_airportInd_airport_id', 'airports', ['airport_id'], ['id'])

    with op.batch_alter_table('airlineInd', schema=None) as batch_op:
        batch_op.drop_index('uq_airline_ind_period')
        batch_op.drop_constraint('fk_airlineInd_indicator_id', type_='foreignkey')
        batch_op.drop_constraint('fk_airlineInd_shipping_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_airlineInd_indicator_id', 'indicators', ['indicator_id'], ['id'])
        batch_op.create_foreign_key('fk_airlineInd_shipping_id', 'shipping', ['shipping_id'], ['id'])
