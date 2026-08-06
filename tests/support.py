"""Общая обвязка тестов: временная БД, состояния схемы, засев справочников.

Каждый тест работает в собственном временном файле. Рабочая БД проекта
(db/database.db) не открывается ни на чтение, ни на запись.
"""

import os
import tempfile
import unittest

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, text

from db.database import _sqlite_pragmas
from db.migrator import _config, upgrade_to_head


def db_url(engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def make_engine(path: str):
    """Движок с теми же прагмами, что настраивает приложение.

    Обработчик берётся из db.database, а не переписывается здесь: иначе тесты
    проверяли бы собственную копию настроек, а не то, с чем работает программа
    (в частности foreign_keys=ON).
    """
    engine = create_engine(f"sqlite:///{path}")
    event.listens_for(engine, "connect")(_sqlite_pragmas)
    return engine


def baseline_revision() -> str:
    """Первая ревизия линии — состояние схемы до перехода на Alembic."""
    return ScriptDirectory.from_config(_config("sqlite://")).get_base()


def make_legacy_db(engine, *, without_year: bool = False, without_parent_id: bool = False) -> None:
    """Приводит БД в состояние «до Alembic»: схема baseline без таблицы версий.

    Так выглядела база, созданная прежним Base.metadata.create_all(). Флаги
    воспроизводят ещё более старые установки, где колонок year и parent_id
    не было и init_db() дописывал их вручную.
    """
    command.upgrade(_config(db_url(engine)), baseline_revision())

    # Правка схемы в обход приложения: отдельное подключение без прагм, иначе
    # включённые внешние ключи не дают пересобрать таблицу показателей.
    surgery = create_engine(db_url(engine))
    try:
        with surgery.begin() as conn:
            conn.execute(text("DROP TABLE alembic_version"))
            if without_year:
                conn.execute(text("ALTER TABLE airlineInd DROP COLUMN year"))
                conn.execute(text("ALTER TABLE airportInd DROP COLUMN year"))
            if without_parent_id:
                # Колонка входит в табличный FK на саму себя, DROP COLUMN её не берёт:
                # воспроизводим таблицу в том виде, в каком она была до parent_id.
                conn.execute(text("""
                    CREATE TABLE indicators_without_parent (
                        id INTEGER NOT NULL,
                        name VARCHAR(50) NOT NULL,
                        code VARCHAR(20) NOT NULL,
                        measure VARCHAR(20) NOT NULL,
                        PRIMARY KEY (id),
                        UNIQUE (code),
                        UNIQUE (id)
                    )
                """))
                conn.execute(text(
                    "INSERT INTO indicators_without_parent SELECT id, name, code, measure FROM indicators"
                ))
                conn.execute(text("DROP TABLE indicators"))
                conn.execute(text("ALTER TABLE indicators_without_parent RENAME TO indicators"))
    finally:
        surgery.dispose()


def seed_reference_data(engine) -> None:
    """Минимальный набор справочников: авиакомпания с рейсом, аэропорт, показатель."""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO airlines (id, code, name) VALUES (1, 'AAA', 'Тестовая АК')"))
        conn.execute(text("INSERT INTO routes (id, type, regularity) VALUES (1, 'trunk', 'regular')"))
        conn.execute(text("INSERT INTO shipping (id, route_id, airline_id) VALUES (1, 1, 1)"))
        conn.execute(text("INSERT INTO airport_localities (id, name) VALUES (1, 'Город')"))
        conn.execute(text("INSERT INTO airports (id, code, name, locality_id) VALUES (1, 'XXX', 'Аэропорт', 1)"))
        conn.execute(text(
            "INSERT INTO indicators (id, name, code, measure) VALUES (1, 'Налет часов', '356', 'час.')"
        ))


def table_ddl(engine, name: str):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = :name"), {"name": name}
        ).scalar()


def scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


class TempDbCase(unittest.TestCase):
    """Тест с пустой временной БД (файл ещё не создан)."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = os.path.join(tmp.name, "test.db")
        self.engine = make_engine(self.db_path)
        self.addCleanup(self.engine.dispose)


class MigratedDbCase(TempDbCase):
    """Тест с БД, поднятой миграциями до актуальной версии."""

    def setUp(self) -> None:
        super().setUp()
        upgrade_to_head(self.engine)
