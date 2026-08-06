from logging.config import fileConfig

from sqlalchemy import create_engine, event, pool
from alembic import context

from db.database import DB_URL
from db.models.entities import Base


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def _db_url() -> str:
    """URL целевой БД: из вызова программно, иначе из db.database.

    Из alembic.ini URL не берётся сознательно — там он относительный, и alembic,
    запущенный не из корня проекта, создал бы вторую пустую БД.
    """
    return config.attributes.get("db_url") or DB_URL


def _migration_engine():
    """Отдельный движок для миграций.

    Внешние ключи на время миграций выключены: render_as_batch пересоздаёт таблицу
    через временную копию, и при включённой проверке ссылки дочерних таблиц уехали бы
    на неё. Целостность проверяется явно после прогона.
    """
    engine = create_engine(_db_url(), poolclass=pool.NullPool)

    @event.listens_for(engine, "connect")
    def _fk_off(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=OFF")
        finally:
            cursor.close()

    return engine


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = _migration_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()

        broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                f"После миграции нарушена ссылочная целостность: {broken}"
            )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
