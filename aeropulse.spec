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
  * assets/ — иконка окна: в exe она вшита ресурсом, но при запуске из
    исходников брать её неоткуда, а окно должно выглядеть одинаково;
  * alembic.ini не нужен: конфиг собирается в коде, файл требуется только
    разработчику для `alembic revision`.
"""

import tomllib
from pathlib import Path

PROJECT_DIR = Path(SPECPATH)
ICON = PROJECT_DIR / "assets" / "AeroPulse.ico"

# Версия берётся из pyproject.toml: одно место на исходники, свойства exe и
# установщик. Расходиться им нельзя — по версии в свойствах файла пользователь
# и определяет, что именно у него установлено.
VERSION = tomllib.loads(
    (PROJECT_DIR / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]


def version_resource() -> str:
    """Сведения о версии для свойств exe. PyInstaller ждёт их отдельным файлом.

    Организация и правообладатель не указываются: в проекте они нигде не названы,
    а придумывать их для свойств исполняемого файла нельзя — это то, по чему
    пользователь судит о происхождении программы.
    """
    numbers = tuple(int(part) for part in VERSION.split("."))[:4]
    numbers += (0,) * (4 - len(numbers))

    # 1049 — русский язык, 1200 — кодовая страница Unicode.
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('041904b0', [
        StringStruct('FileDescription',
                     'Учёт статистической отчётности гражданской авиации'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', 'AeroPulse'),
        StringStruct('OriginalFilename', 'AeroPulse.exe'),
        StringStruct('ProductName', 'AeroPulse'),
        StringStruct('ProductVersion', '{VERSION}'),
      ]),
    ]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])]),
  ],
)
"""
    target = Path(workpath) / "version_info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


datas = [
    ("migrations", "migrations"),
    ("forms/UIs", "forms/UIs"),
    ("assets/AeroPulse.ico", "assets"),
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
    # Окно без консоли: диагностика идёт в aeropulse.log в каталоге данных
    # (INFRA-2), а не в stdout, которого в этом режиме нет.
    console=False,
    icon=str(ICON),
    version=version_resource(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AeroPulse",
)
