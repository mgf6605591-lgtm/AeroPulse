import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_app_dir() -> Path:
    """Каталог приложения: рядом с exe (PyInstaller) или корень проекта (разработка)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Путь к ресурсу внутри проекта или распакованного бандла PyInstaller."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", get_app_dir()))
    else:
        base = get_app_dir()
    return base.joinpath(*parts)
