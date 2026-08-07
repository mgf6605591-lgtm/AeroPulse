# -*- mode: python ; coding: utf-8 -*-
"""Спека сборки exe (INFRA-3).

Сборка:
    pyinstaller aeropulse.spec

Собранное лежит в dist/AeroPulse/. Рядом с exe приложение создаёт db/database.db,
каталог db/backups/ и aeropulse.log — поэтому ставить его нужно туда, где у
пользователя есть право записи. Установка в C:\\Program Files без прав на запись
даёт ровно тот отказ, о котором приложение теперь честно сообщает окном (BUG-15).

Что обязательно попадает внутрь:
  * migrations/ — схема приводится к актуальной ревизии при каждом запуске
    (db/migrator.py ищет каталог через resource_path, то есть внутри бандла);
  * forms/UIs/ — разметка окна входа загружается через uic во время работы;
  * alembic.ini не нужен: конфиг собирается в коде, файл требуется только
    разработчику для `alembic revision`.
"""

datas = [
    ("migrations", "migrations"),
    ("forms/UIs", "forms/UIs"),
]

# Alembic находит ревизии по файлам, а не по импортам, поэтому PyInstaller их
# не видит и в бандл сам не кладёт.
hiddenimports = [
    "alembic.runtime.migration",
    "sqlalchemy.dialects.sqlite",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Тяжёлые зависимости, которые в приложении не используются. scikit-learn
    # числится в requirements.txt (INFRA-4) и тянет в сборку десятки мегабайт.
    excludes=["scikit-learn", "sklearn", "matplotlib", "tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AeroPulse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Окно без консоли: диагностика идёт в aeropulse.log рядом с exe (INFRA-2),
    # а не в stdout, которого в этом режиме нет.
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AeroPulse",
)
