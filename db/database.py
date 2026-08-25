from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from contextlib import contextmanager

from utils.paths import get_data_dir


def _resolve_db_path() -> Path:
    db_path = get_data_dir() / "db" / "database.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


# Абсолютный путь к БД: в установленной программе — в каталоге данных
# пользователя, в разработке — db/database.db в корне проекта. Рядом с exe база
# больше не лежит: тот каталог принадлежит установщику, и обновление его
# перезаписывает.
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


def db_path() -> Path:
    """Путь к файлу базы — для операций над самим файлом (резервные копии)."""
    return _db_path


# Одна фабрика на приложение. Прежде `sessionmaker` создавался заново при каждом
# обращении к `get_session()` — на каждый список фильтра, каждую строку импорта,
# каждую перезагрузку отчёта (PERF-5).
_session_factory = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session():
    session = _session_factory()
    try:
        yield session
    except Exception:
        # `close()` откатывает незавершённую транзакцию и сам — проверено, — так
        # что дело не в целостности данных: откат здесь стоит затем, чтобы
        # намерение читалось на месте, а не выводилось из документации SQLAlchemy.
        session.rollback()
        raise
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
