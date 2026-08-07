"""
Настройка путей к Qt platform plugins (qwindows.dll) до создания QApplication.
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def ensure_qt_platform_plugins() -> None:
    """
    Снимает пустой QT_PLUGIN_PATH (из-за него в логе «... in ""») и выставляет
    каталоги, где лежит qwindows.dll.
    """
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        if os.environ.get(key) == "":
            del os.environ[key]

    # Ищется qwindows.dll — плагин, который существует только под Windows.
    # На остальных системах поиск заведомо ничего не находил, но доходил до
    # рекурсивного обхода site-packages, и так при каждом запуске (PERF-6).
    if sys.platform != "win32":
        return

    def _try_plugins_dir(plugins_dir: Path) -> bool:
        plat = plugins_dir / "platforms"
        if not plat.is_dir():
            return False
        if not any(plat.glob("qwindows*.dll")):
            return False
        os.environ["QT_PLUGIN_PATH"] = str(plugins_dir)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plat)
        return True

    try:
        from PyQt6.QtCore import QLibraryInfo

        p = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        if p and _try_plugins_dir(Path(p)):
            return
    except Exception:
        pass

    try:
        import PyQt6

        base = Path(PyQt6.__file__).resolve().parent
        for plugins_dir in (base / "Qt6" / "plugins",):
            if _try_plugins_dir(plugins_dir):
                return
        for dll in base.rglob("qwindows*.dll"):
            if "platforms" in dll.parts:
                if _try_plugins_dir(dll.parent.parent):
                    return
    except ImportError:
        pass

    roots: list[Path] = []
    try:
        roots.extend(Path(p) for p in site.getsitepackages() if p)
    except Exception:
        pass
    try:
        u = site.getusersitepackages()
        if u:
            roots.append(Path(u))
    except Exception:
        pass

    for sp in roots:
        for plugins_dir in (
            sp / "PyQt6" / "Qt6" / "plugins",
            sp / "PyQt6" / "Qt" / "plugins",
        ):
            if _try_plugins_dir(plugins_dir):
                return
        pyqt6 = sp / "PyQt6"
        if pyqt6.is_dir():
            for dll in pyqt6.rglob("qwindows*.dll"):
                if "platforms" in dll.parts and _try_plugins_dir(dll.parent.parent):
                    return
