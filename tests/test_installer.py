"""Дистрибутив под Windows: спека, иконка, скрипт установщика, задача сборки.

Ни одно из этого не проверяется прогоном приложения: ошибка здесь всплывает у
пользователя после установки — окном «не удалось открыть окно входа», пустыми
свойствами файла или иконкой-заглушкой. Собрать exe в тестах нельзя (нужен
Windows), поэтому проверяется то, из чего он собирается.
"""

import re
import struct
import tempfile
import tomllib
import unittest
from pathlib import Path, PureWindowsPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC = PROJECT_ROOT / "aeropulse.spec"
ICON = PROJECT_ROOT / "assets" / "AeroPulse.ico"
INNO = PROJECT_ROOT / "installer" / "AeroPulse.iss"
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "installer.yml"
BUILD_REQUIREMENTS = PROJECT_ROOT / "requirements-build.txt"


def project_version() -> str:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


class _SpecStub:
    """Заглушка классов PyInstaller: запоминает то, что ей передали."""

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        _SpecStub.captured.update(kwargs)

    def __getattr__(self, name):
        return []

    captured: dict = {}


def run_spec() -> tuple[dict, dict]:
    """Выполняет спеку так, как это делает PyInstaller, и возвращает её итог.

    Спека — обычный Python, исполняемый в подготовленном пространстве имён.
    Проверять её разбором текста значило бы проверять не то, что выполнится.
    """
    _SpecStub.captured = {}
    with tempfile.TemporaryDirectory() as work:
        namespace = {
            "__file__": str(SPEC),
            "SPECPATH": str(PROJECT_ROOT),
            "workpath": work,
            "DISTPATH": str(PROJECT_ROOT / "dist"),
            "Analysis": _SpecStub,
            "PYZ": _SpecStub,
            "EXE": _SpecStub,
            "COLLECT": _SpecStub,
        }
        code = compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec")
        exec(code, namespace)
        captured = dict(_SpecStub.captured)
        # Файл сведений о версии живёт в рабочем каталоге сборки — прочитать его
        # надо до того, как каталог исчезнет.
        captured["version_text"] = Path(captured["version"]).read_text(encoding="utf-8")
    return namespace, captured


class SpecTest(unittest.TestCase):
    """Спека собирает exe с иконкой, версией и всем, что нужно во время работы."""

    @classmethod
    def setUpClass(cls):
        cls.namespace, cls.captured = run_spec()

    def test_version_comes_from_pyproject(self):
        """Одно место на исходники, свойства exe и установщик."""
        self.assertEqual(project_version(), self.namespace["VERSION"])

    def test_icon_is_bundled_and_exists(self):
        self.assertTrue(Path(self.namespace["ICON"]).is_file())
        self.assertEqual(str(ICON), self.captured["icon"])

    def test_runtime_resources_are_included(self):
        """Без них exe запускается, а программа — нет."""
        destinations = {destination for _, destination in self.namespace["datas"]}
        self.assertEqual({"migrations", "forms/UIs", "assets"}, destinations)

    def test_sources_of_bundled_resources_exist(self):
        for source, _ in self.namespace["datas"]:
            self.assertTrue((PROJECT_ROOT / source).exists(), source)

    def test_window_has_no_console(self):
        self.assertFalse(self.captured["console"])


class VersionResourceTest(unittest.TestCase):
    """Свойства файла: то, по чему пользователь узнаёт, что у него установлено."""

    @classmethod
    def setUpClass(cls):
        _, cls.captured = run_spec()
        cls.strings, cls.fixed = cls.parse(cls.captured["version_text"])

    @staticmethod
    def parse(text: str) -> tuple[dict, dict]:
        """Разбирает файл так же, как PyInstaller, — исполнением."""
        seen: dict[str, list] = {}

        def factory(name):
            def record(*args, **kwargs):
                seen.setdefault(name, []).append((args, kwargs))
                return (name, args, kwargs)
            return record

        names = ("VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable",
                 "StringStruct", "VarFileInfo", "VarStruct")
        eval(compile(text, "version_info", "eval"), {n: factory(n) for n in names})

        strings = dict(args for args, _ in seen["StringStruct"])
        return strings, seen["FixedFileInfo"][0][1]

    def test_it_is_valid_for_pyinstaller(self):
        """Файл со сбитым синтаксисом уронил бы сборку, а не тихо пропал."""
        self.assertIn("ProductName", self.strings)

    def test_versions_match_the_project(self):
        version = project_version()
        self.assertEqual(version, self.strings["FileVersion"])
        self.assertEqual(version, self.strings["ProductVersion"])

    def test_numeric_version_has_four_parts(self):
        """Windows хранит версию четырьмя числами, короче она туда не ложится."""
        numbers = self.fixed["filevers"]
        self.assertEqual(4, len(numbers))
        self.assertEqual(tuple(int(p) for p in project_version().split(".")),
                         numbers[:len(project_version().split("."))])

    def test_the_program_is_named_and_described(self):
        self.assertEqual("AeroPulse", self.strings["ProductName"])
        self.assertEqual("AeroPulse.exe", self.strings["OriginalFilename"])
        self.assertIn("отчётности", self.strings["FileDescription"])

    def test_no_organisation_is_invented(self):
        """В проекте не названы ни организация, ни правообладатель."""
        self.assertNotIn("CompanyName", self.strings)
        self.assertNotIn("LegalCopyright", self.strings)


class IconTest(unittest.TestCase):
    """Иконка: многоразмерный .ico, иначе Windows отмасштабирует одну и ту же."""

    @classmethod
    def setUpClass(cls):
        cls.data = ICON.read_bytes()

    def entries(self):
        _, kind, count = struct.unpack("<HHH", self.data[:6])
        self.assertEqual(1, kind, "тип 1 — иконка, 2 — курсор")
        for index in range(count):
            offset = 6 + 16 * index
            width, height, _, _, _, bits, size, at = struct.unpack(
                "<BBBBHHII", self.data[offset:offset + 16])
            yield (width or 256), (height or 256), bits, self.data[at:at + size]

    def test_it_carries_the_sizes_windows_asks_for(self):
        sizes = {width for width, _, _, _ in self.entries()}
        # 16 — заголовок окна и панель задач, 32 — рабочий стол,
        # 256 — крупные значки проводника и окно установщика.
        self.assertLessEqual({16, 32, 48, 256}, sizes)

    def test_every_entry_is_a_real_image_of_its_size(self):
        for width, height, _, blob in self.entries():
            self.assertEqual(b"\x89PNG\r\n\x1a\n", blob[:8])
            self.assertEqual((width, height), struct.unpack(">II", blob[16:24]))

    def test_entries_keep_transparency(self):
        """32 бита на пиксель — иначе у иконки будет непрозрачный фон."""
        for width, _, bits, _ in self.entries():
            self.assertEqual(32, bits, f"{width}px")

    def test_the_source_image_is_kept(self):
        """Из PNG иконка и пересобирается; без него следующий размер не добавить."""
        self.assertTrue((PROJECT_ROOT / "assets" / "AeroPulse.png").is_file())


class InnoScriptTest(unittest.TestCase):
    """Скрипт установщика."""

    @classmethod
    def setUpClass(cls):
        cls.text = INNO.read_text(encoding="utf-8")

    def setting(self, name: str) -> str:
        match = re.search(rf"^{name}=(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(match, f"в скрипте нет {name}")
        return match.group(1).strip()

    def test_it_installs_for_the_current_user(self):
        """Так установка и обновление обходятся без прав администратора."""
        self.assertEqual("lowest", self.setting("PrivilegesRequired"))

    def test_it_does_not_ask_about_the_install_mode(self):
        """Режим выбран заранее; лишний вопрос пользователю здесь не нужен."""
        self.assertNotIn("PrivilegesRequiredOverridesAllowed", self.text)

    def test_app_id_is_a_fixed_guid(self):
        """По нему Windows отличает обновление от второй установки рядом."""
        app_id = self.setting("AppId")
        self.assertRegex(app_id, r"^\{\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")

    def test_user_data_survives_uninstall(self):
        """Раздела удаления данных быть не должно: там отчётность за годы."""
        # Именно раздел, а не упоминание: в скрипте объяснено, почему его нет.
        self.assertIsNone(re.search(r"^\[UninstallDelete\]", self.text, re.MULTILINE))

    def test_version_is_not_written_by_hand(self):
        """Иначе она разойдётся с pyproject.toml — вопрос только когда."""
        self.assertIn("GetStringFileInfo", self.text)
        self.assertNotIn(project_version(), self.text)

    def test_it_points_at_the_icon_and_the_build(self):
        # Пути в скрипте записаны по-виндовому; тест идёт и на macOS, и на Linux.
        icon = PureWindowsPath(self.setting("SetupIconFile"))
        self.assertTrue((INNO.parent / Path(*icon.parts)).resolve().is_file())
        self.assertIn(r"..\dist\AeroPulse", self.text)

    def test_it_refuses_windows_too_old_for_qt(self):
        """Qt 6.10 живёт с Windows 10; отказ внятнее, чем незапуск."""
        self.assertEqual("10.0", self.setting("MinVersion"))


class BuildWorkflowTest(unittest.TestCase):
    """Задача сборки в CI."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_it_builds_on_windows(self):
        self.assertIn("runs-on: windows-latest", self.text)

    def test_it_checks_every_bundled_resource(self):
        """Проверка состава бандла обязана знать обо всём, что кладёт спека."""
        namespace, _ = run_spec()
        for _, destination in namespace["datas"]:
            self.assertIn(destination.replace("/", "\\"), self.text)

    def test_it_builds_the_installer_too(self):
        self.assertIn("innosetup", self.text)
        self.assertIn(r"iscc installer\AeroPulse.iss", self.text)

    def test_build_tools_are_pinned(self):
        """Версия PyInstaller решает, что окажется внутри exe (INFRA-4)."""
        lines = [line.strip() for line in
                 BUILD_REQUIREMENTS.read_text(encoding="utf-8").splitlines()]
        packages = [line.split("#")[0].strip() for line in lines
                    if line and not line.startswith("#")]
        self.assertTrue(packages)
        for package in packages:
            self.assertRegex(package, r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+$")
        self.assertIn("requirements-build.txt", self.text)


if __name__ == "__main__":
    unittest.main()
