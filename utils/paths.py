import os
import shutil
import sys
from pathlib import Path

APP_NAME = "AeroPulse"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_app_dir() -> Path:
    """Каталог приложения: рядом с exe (PyInstaller) или корень проекта (разработка)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Каталог пользовательских данных: база, копии базы и журнал приложения.

    В разработке — корень проекта: рабочая база лежит там, где её ищет
    разработчик, и путь не зависит от машины.

    В установленной программе — каталог профиля пользователя. Данные обязаны
    лежать не там, где сама программа: каталог программы обновление
    перезаписывает целиком, а удаление сносит вместе со всем содержимым, и
    отчётность за несколько лет исчезла бы молча. Установка «только для меня»
    от прав администратора не зависит, но это ничего не меняет: писать в свой
    каталог программе всё равно нельзя.
    """
    if not is_frozen():
        return get_app_dir()
    return _user_data_dir()


def _user_data_dir() -> Path:
    """Каталог данных пользователя по правилам операционной системы."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        # LOCALAPPDATA задан в любом штатном сеансе Windows; запасной путь нужен
        # для урезанного окружения — службы, задания планировщика, sudo-подобные
        # запуски, — где переменная не наследуется.
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / APP_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_NAME


def resource_path(*parts: str) -> Path:
    """Путь к ресурсу внутри проекта или распакованного бандла PyInstaller."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", get_app_dir()))
    else:
        base = get_app_dir()
    return base.joinpath(*parts)


def migrate_legacy_data_dir(source: Path | None = None,
                            target: Path | None = None) -> list[str]:
    """Переносит данные из каталога программы в каталог пользователя.

    До появления установщика база, копии и журнал лежали рядом с exe, и README
    честно просил ставить программу туда, где есть право записи. Теперь программу
    ставит установщик, а её каталог обновление перезаписывает — оставленные там
    данные однажды исчезли бы вместе с прежней версией.

    Переносится всё или ничего: у базы в режиме WAL часть данных лежит в
    отдельном файле журнала, и перенести один файл из трёх значит получить
    повреждённую базу. Если в новом каталоге база уже есть, не трогается ничего —
    там работают, а рядом с exe лежит прошлое.

    Возвращает имена перенесённого; пустой список — переносить было нечего.
    Аргументы нужны тестам: в разработке оба каталога и так совпадают.
    """
    source = source or get_app_dir()
    target = target or get_data_dir()
    if source.resolve() == target.resolve():
        return []

    # logging_setup сам импортирует этот модуль — импорт локальный, иначе цикл.
    from utils.logging_setup import LOG_FILE_NAME

    if (target / "db" / "database.db").exists():
        return []

    database = source / "db" / "database.db"
    if not database.is_file():
        # Базы нет — значит, нет и того, ради чего перенос затевался. Копии и
        # журнал без неё самостоятельной ценности не имеют.
        return []

    items = [
        *(Path("db") / f"database.db{suffix}" for suffix in ("", "-wal", "-shm")),
        *(Path("db") / "backups" / path.name
          for path in sorted((source / "db" / "backups").glob("database-*.db"))),
        *(Path(path.name) for path in sorted(source.glob(f"{LOG_FILE_NAME}*"))),
    ]

    moved: list[str] = []
    for item in items:
        old = source / item
        if not old.is_file():
            continue
        new = target / item
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))
        moved.append(item.as_posix())

    # Опустевшие каталоги убираются следом. Иначе рядом с exe остаётся db/ с
    # backups/ внутри, и каталог установки перестаёт совпадать с тем, что
    # положил установщик, — а именно по такому расхождению и замечают, что
    # программа пишет туда, куда не должна.
    #
    # rmdir, а не удаление поддерева: он снимает только то, что действительно
    # опустело. Если пользователь держал в db/ что-то своё, вызов не пройдёт, и
    # это правильный исход — чужое здесь трогать не за что.
    for leftover in (source / "db" / "backups", source / "db"):
        try:
            leftover.rmdir()
        except OSError:
            pass

    return moved
