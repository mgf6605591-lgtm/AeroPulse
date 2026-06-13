from pathlib import Path

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from contextlib import contextmanager

from db.models.entities import Base, User
from db.models.enums import UserPosition
from utils.paths import get_app_dir, is_frozen

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "123"
DEFAULT_ADMIN_EMAIL = "admin@localhost"


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
    finally:
        cursor.close()

Session = sessionmaker(engine)


@contextmanager
def get_session():
    Session_local = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session_local()
    try:
        yield session
    finally:
        session.close()


def init_db():
    """Создание таблиц и миграция (одна транзакция — меньше конфликтов блокировок SQLite)."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info('airlineInd')"))
        columns = [row[1] for row in result.fetchall()]
        if "year" not in columns:
            conn.execute(text("ALTER TABLE airlineInd ADD COLUMN year INTEGER DEFAULT 2025"))

        result = conn.execute(text("PRAGMA table_info('airportInd')"))
        columns = [row[1] for row in result.fetchall()]
        if "year" not in columns:
            conn.execute(text("ALTER TABLE airportInd ADD COLUMN year INTEGER DEFAULT 2025"))

        result = conn.execute(text("PRAGMA table_info('indicators')"))
        ind_cols = [row[1] for row in result.fetchall()]
        if "parent_id" not in ind_cols:
            conn.execute(
                text(
                    "ALTER TABLE indicators ADD COLUMN parent_id INTEGER REFERENCES indicators(id)"
                )
            )

        conn.execute(
            text("""
            UPDATE indicators
            SET parent_id = (SELECT id FROM indicators AS p WHERE p.code = '450' LIMIT 1)
            WHERE code IN ('450пас', '450гр', '450пч')
              AND parent_id IS NULL
              AND EXISTS (SELECT 1 FROM indicators AS p WHERE p.code = '450')
        """)
        )

    _seed_default_admin()


def _seed_default_admin() -> None:
    """Создаёт учётную запись администратора, если в БД ещё нет пользователя admin."""
    session = Session()
    try:
        exists = session.execute(
            select(User.id).where(User.username == DEFAULT_ADMIN_USERNAME).limit(1)
        ).first()
        if exists is not None:
            return

        session.add(
            User(
                username=DEFAULT_ADMIN_USERNAME,
                email=DEFAULT_ADMIN_EMAIL,
                position=UserPosition.admin,
                password_hash=DEFAULT_ADMIN_PASSWORD,
            )
        )
        session.commit()
    finally:
        session.close()
