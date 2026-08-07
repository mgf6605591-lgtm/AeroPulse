"""Поиск плагинов Qt при старте (PERF-6).

Искался `qwindows.dll` — плагин, который существует только под Windows. На
остальных системах поиск заведомо ничего не находил, но доходил до рекурсивного
обхода site-packages, и так при каждом запуске.
"""

import unittest
from unittest.mock import patch

from utils import qt_plugins


class PluginSearchTest(unittest.TestCase):
    def test_no_search_outside_windows(self):
        """Обход site-packages не должен даже начинаться."""
        with patch.object(qt_plugins.sys, "platform", "darwin"), \
             patch.object(qt_plugins.site, "getsitepackages") as get_sitepackages:
            qt_plugins.ensure_qt_platform_plugins()

        get_sitepackages.assert_not_called()

    def test_empty_plugin_path_is_cleared_anywhere(self):
        """Пустой QT_PLUGIN_PATH мешает и вне Windows — это делается до выхода."""
        with patch.dict(qt_plugins.os.environ, {"QT_PLUGIN_PATH": ""}, clear=False):
            with patch.object(qt_plugins.sys, "platform", "darwin"):
                qt_plugins.ensure_qt_platform_plugins()

            self.assertNotIn("QT_PLUGIN_PATH", qt_plugins.os.environ)

    def test_search_still_runs_on_windows(self):
        with patch.object(qt_plugins.sys, "platform", "win32"), \
             patch.object(qt_plugins.site, "getsitepackages", return_value=[]) as get_sitepackages, \
             patch.object(qt_plugins.site, "getusersitepackages", return_value=""):
            qt_plugins.ensure_qt_platform_plugins()

        get_sitepackages.assert_called_once()


if __name__ == "__main__":
    unittest.main()
