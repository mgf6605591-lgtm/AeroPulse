# -*- mode: python ; coding: utf-8 -*-
"""Спека сборки exe (INFRA-3).

Сборка:
    pyinstaller aeropulse.spec

Собранное лежит в dist/AeroPulse/. Своих данных приложение туда не пишет: база,
её копии и журнал живут в каталоге пользователя (utils.paths.get_data_dir), а
каталог установки остаётся тем, чем и должен быть, — принадлежащим установщику и
доступным только на чтение.

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
    # Тяжёлые пакеты, которые приложению не нужны, но могут оказаться в окружении
    # сборки и уехать в дистрибутив. scikit-learn отсюда убран вместе с самой
    # зависимостью: он числился в requirements.txt, не используясь ни разу, и
    # тянул в сборку десятки мегабайт (INFRA-4).
    excludes=["matplotlib", "tkinter", "pytest"],
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
