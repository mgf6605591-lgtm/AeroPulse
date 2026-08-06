"""Приведение схемы БД к актуальной версии миграциями Alembic при старте приложения."""

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from utils.paths import resource_path


def _config(db_url: str) -> Config:
    """Конфиг собирается в коде: alembic.ini нужен только разработчику для `alembic revision`.

    script_location считается через resource_path, поэтому каталог migrations
    находится и в разработке, и внутри бандла PyInstaller. URL передаётся явно:
    иначе env.py взял бы db.database.DB_URL и мог уехать на другую БД, чем та,
    которую проверил вызывающий.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(resource_path("migrations")))
    cfg.attributes["db_url"] = db_url
    return cfg


def upgrade_to_head(engine) -> None:
    """Применяет непринятые миграции; при необходимости сначала «усыновляет» старую БД."""
    cfg = _config(engine.url.render_as_string(hide_password=False))
    tables = set(inspect(engine).get_table_names())

    # БД, созданная прежним create_all(): схема уже соответствует baseline, но
    # Alembic о ней не знает. Пересоздавать таблицы нельзя — отмечаем ревизию.
    if tables and "alembic_version" not in tables:
        _adopt_legacy_db(engine)
        command.stamp(cfg, ScriptDirectory.from_config(cfg).get_base())

    command.upgrade(cfg, "head")


def _adopt_legacy_db(engine) -> None:
    """Доводит БД прежних версий до состояния baseline.

    Те же шаги, что раньше выполнялись при каждом запуске в init_db(). Выполняются
    один раз: после stamp сюда управление больше не попадает.
    """
    with engine.begin() as conn:
        for table in ("airlineInd", "airportInd"):
            columns = [row[1] for row in conn.execute(text(f"PRAGMA table_info('{table}')"))]
            if "year" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN year INTEGER DEFAULT 2025"))

        ind_cols = [row[1] for row in conn.execute(text("PRAGMA table_info('indicators')"))]
        if "parent_id" not in ind_cols:
            conn.execute(
                text("ALTER TABLE indicators ADD COLUMN parent_id INTEGER REFERENCES indicators(id)")
            )

        # Разовый ремонт связей детализации тоннокилометража; дальше их проставляет
        # импортёр (DataImporter._link_detail_indicators).
        conn.execute(
            text("""
            UPDATE indicators
            SET parent_id = (SELECT id FROM indicators AS p WHERE p.code = '450' LIMIT 1)
            WHERE code IN ('450пас', '450гр', '450пч')
              AND parent_id IS NULL
              AND EXISTS (SELECT 1 FROM indicators AS p WHERE p.code = '450')
        """)
        )
