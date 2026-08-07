"""журнал загрузок и удалений

Заводит таблицу import_log (FUNC-5). О происхождении данных не сохранялось
ничего: имя файла упоминалось только в сообщении на экране и никуда не
записывалось, удаления не журналировались вовсе. При расхождении цифр установить,
из какого файла пришло значение и не затёр ли его повторный импорт, было нечем.

Внешних ключей на предприятия у журнала нет намеренно: он должен пережить
удаление того, о чём рассказывает.

Revision ID: e2b8f30d1a47
Revises: d4a17c9e5b82
Create Date: 2026-08-07 18:12:55.410882

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b8f30d1a47'
down_revision: Union[str, Sequence[str], None] = 'd4a17c9e5b82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'import_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('user', sa.String(length=50), nullable=True),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('entity_type', sa.String(length=20), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('entity_name', sa.String(length=100), nullable=True),
        sa.Column('month', sa.Integer(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('imported', sa.Integer(), nullable=False),
        sa.Column('updated', sa.Integer(), nullable=False),
        sa.Column('removed', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('import_log')
