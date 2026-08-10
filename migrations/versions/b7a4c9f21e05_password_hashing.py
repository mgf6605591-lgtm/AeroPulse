"""хеширование паролей и признак обязательной смены

Закрывает хранение паролей открытым текстом (SEC-1). Поле называлось
`password_hash`, но хранило сам пароль: в поставляемой БД строка пользователя
была `(1, 'admin', 'admin@localhost', 'admin', '123')`.

Ревизия переводит уже существующие пароли в хеши scrypt и помечает такие учётки
как требующие смены пароля при первом входе. Пометка обязательна: значение,
лежавшее открытым текстом, к этому моменту могло уйти куда угодно — файл БД
находится рядом с exe, а его снимок остался в истории git (SEC-5).

Обратный переход паролей не восстанавливает: хеш необратим. После downgrade
прежний код сравнит введённый пароль со строкой хеша и не пустит никого — это
отмечено в самой функции.

Revision ID: b7a4c9f21e05
Revises: 6fd62d1c1c87
Create Date: 2026-08-07 10:12:44.180233

"""
from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from utils.passwords import hash_password, is_hashed


# revision identifiers, used by Alembic.
revision: str = 'b7a4c9f21e05'
down_revision: str | Sequence[str] | None = '6fd62d1c1c87'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Лёгкая проекция таблицы: модель здесь не используется, иначе ревизия начнёт
# зависеть от текущего состояния entities.py, а не от состояния схемы на свой момент.
users = sa.table(
    'users',
    sa.column('id', sa.Integer),
    sa.column('password_hash', sa.String),
    sa.column('must_change_password', sa.Boolean),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='0'),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.select(users.c.id, users.c.password_hash)).fetchall()
    for user_id, stored in rows:
        if is_hashed(stored):
            continue
        conn.execute(
            users.update()
            .where(users.c.id == user_id)
            .values(password_hash=hash_password(stored or ""), must_change_password=True)
        )


def downgrade() -> None:
    """Downgrade schema.

    Пароли остаются хешами: восстановить их нечем. После отката вход работать не
    будет, пока пароли не заданы заново.
    """
    op.drop_column('users', 'must_change_password')
