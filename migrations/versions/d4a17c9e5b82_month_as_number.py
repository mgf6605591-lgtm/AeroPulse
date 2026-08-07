"""месяц хранится числом 1…12, а не именем

Закрывает фильтрацию периода в Python (PERF-1). Месяц лежал строкой («January»),
а имена несравнимы по порядку: SQL мог ограничить выборку только по годам, и
точный отбор по месяцу выполнялся перебором уже поднятых записей. Номер месяца
упорядочен, поэтому весь период уходит в запрос одним условием.

Имена переводятся в номера до смены типа колонки: SQLite не преобразует
«January» в число сам — он положил бы имя в колонку с числовым сродством как
есть, и записи стали бы невидимы для любого сравнения периода.

Revision ID: d4a17c9e5b82
Revises: c8f1b4d27a63
Create Date: 2026-08-07 16:41:07.902355

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a17c9e5b82'
down_revision: Union[str, Sequence[str], None] = 'c8f1b4d27a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERIOD_TABLES = ('airlineInd', 'airportInd')

MONTH_NAMES = (
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
)


def _case_sql(mapping: dict, column: str = 'month') -> str:
    """CASE-выражение перевода: сопоставления перечислены явно, без вычислений."""
    whens = " ".join(f"WHEN '{key}' THEN '{value}'" for key, value in mapping.items())
    return f"CASE {column} {whens} ELSE {column} END"


def upgrade() -> None:
    names_to_numbers = {name: number for number, name in enumerate(MONTH_NAMES, start=1)}
    for table in PERIOD_TABLES:
        op.execute(f'UPDATE "{table}" SET month = {_case_sql(names_to_numbers)}')
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                'month',
                existing_type=sa.String(length=9),
                type_=sa.Integer(),
                existing_nullable=False,
            )


def downgrade() -> None:
    numbers_to_names = {number: name for number, name in enumerate(MONTH_NAMES, start=1)}
    for table in PERIOD_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                'month',
                existing_type=sa.Integer(),
                type_=sa.String(length=9),
                existing_nullable=False,
            )
        op.execute(f'UPDATE "{table}" SET month = {_case_sql(numbers_to_names)}')
