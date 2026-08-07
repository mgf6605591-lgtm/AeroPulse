from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from contextlib import contextmanager

from utils.paths import get_app_dir, is_frozen


def _resolve_db_path() -> Path:
    if is_frozen():
        db_path = get_app_dir() / "db" / "database.db"
    else:
        db_path = Path(__file__).resolve().parent / "database.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


# Абсолютный путь к БД: в exe — рядом с main.exe, в разработке — db/database.db.
_db_path = _resolve_db_path()
DB_URL = f"sqlite:///{_db_path.as_posix()}"

# SQLite: таймаут ожидания блокировки, WAL, NullPool — устраняет sqlite3.OperationalError: database is locked
engine = create_engine(
    DB_URL,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 60.0,
    },
    poolclass=NullPool,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # SQLite проверяет внешние ключи только когда это включено на соединении;
        # без этого все FOREIGN KEY в схеме декоративны.
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


@contextmanager
def get_session():
    Session_local = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session_local()
    try:
        yield session
    finally:
        session.close()


def init_db():
    """Схема приводится к актуальной версии миграциями — правки только через Alembic.

    Учётная запись здесь больше не заводится (SEC-2). Прежний `_seed_default_admin()`
    создавал `admin` с паролем `123` при каждом запуске: удалить такую учётку через
    интерфейс было невозможно — на следующем старте она появлялась снова, а пароль
    к ней знал любой, у кого есть исходники или собранный exe. Первого администратора
    заводит пользователь в окне первичной настройки (`forms.widgets.account_dialogs`).
    """
    # Локальный импорт: env.py миграций импортирует этот модуль.
    from db.migrator import upgrade_to_head

    upgrade_to_head(engine)
