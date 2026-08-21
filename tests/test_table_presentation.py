"""Слой представления таблиц: где он лежит, как показывает числа и что даёт делать мышью.

Один блок на семь пунктов реестра, потому что все они жили в трёх файлах:
двух моделях Qt и заголовке таблицы. Файлы лежали в `db/models/` рядом с
описанием схемы (ARCH-3), и правка любого из них требовала сначала решить,
слой это данных или интерфейса.

* ARCH-3 — `db/` больше не тянет PyQt6: пакет данных поднимается без GUI.
* BUG-20 — подпись месяца видна и после прокрутки вправо.
* BUG-10 — ширину колонки снова можно тянуть мышью.
* BUG-12 — `setData` вернулся Qt: моделям он больше не принадлежит.
* BUG-13 — роль по умолчанию у `data()` — `DisplayRole`, а не сам класс ролей.
* BUG-26 — число в подробной таблице выглядит как в сводной.
* PERF-7 — выравнивание не трогает записи при каждой перерисовке.

Окна создаются на платформе offscreen — на экране не появляется ничего.
"""

import os
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QAbstractItemView, QApplication, QTableView
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])


if HAS_QT:
    from forms.models.pivot_dict_model import PivotDictModel
    from forms.models.roles import RAW_VALUE_ROLE
    from forms.models.sqlalchemy_table_model import SQLAlchemyTableModel
    from forms.widgets.multilevel_header import (
        TEXT_MARGIN,
        MultiLevelHeaderView,
        wrap_header_text,
    )


# --- ARCH-3: слой данных без интерфейса ------------------------------------

# Запрет ставится подменой в sys.modules: так `import PyQt6` падает и в том
# случае, если пакет установлен, — а он установлен, иначе остальные проверки
# этого файла не запускались бы.
_IMPORT_DB_WITHOUT_QT = """
import sys
sys.modules['PyQt6'] = None
try:
    import PyQt6  # noqa: F401
except ImportError:
    pass
else:
    raise AssertionError('запрет на PyQt6 не сработал — проверка ничего не значит')

import db.backup            # noqa: F401
import db.database          # noqa: F401
import db.migrator          # noqa: F401
import db.models.entities   # noqa: F401
import db.models.enums      # noqa: F401
import db.models.types      # noqa: F401
"""


class DatabaseLayerNeedsNoGuiTest(unittest.TestCase):
    """ARCH-3: три файла в `db/models/` не имели отношения к базе.

    Два были `QAbstractTableModel`, третий — виджет заголовка. Из-за них
    `import db.models.*` тянул за собой PyQt6, и слой данных нельзя было
    использовать без GUI.
    """

    def test_db_package_imports_without_pyqt(self):
        result = subprocess.run(
            [sys.executable, "-c", _IMPORT_DB_WITHOUT_QT],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_no_source_under_db_mentions_pyqt(self):
        """Проверка на будущее: следующий Qt-файл не должен приехать обратно."""
        offenders = [
            path.relative_to(PROJECT_ROOT)
            for path in (PROJECT_ROOT / "db").rglob("*.py")
            if "PyQt6" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)


# --- Заголовок таблицы ------------------------------------------------------

@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class HeaderCase(unittest.TestCase):
    """Таблица с двухуровневым заголовком: 16 колонок по 100 px, группы по четыре."""

    COLUMNS = 16
    COLUMN_WIDTH = 100
    GROUPS = [(0, 3, "Январь"), (4, 7, "Февраль"), (8, 11, "Март"), (12, 15, "Апрель")]

    def setUp(self):
        keys = [f"k{i}" for i in range(self.COLUMNS)]
        headers = [f"колонка {i}" for i in range(self.COLUMNS)]

        self.view = QTableView()
        self.addCleanup(self.view.deleteLater)
        self.header = MultiLevelHeaderView(self.view)
        self.view.setHorizontalHeader(self.header)
        # Прокрутка по пикселям, а не по ячейкам: тесту нужно поставить границу
        # группы в заданное место, а не «примерно туда».
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self.model = PivotDictModel()
        self.model.set_source_data([{k: 1 for k in keys}], headers, keys)
        self.view.setModel(self.model)
        self.header.set_groups(self.GROUPS)
        for col in range(self.COLUMNS):
            self.view.setColumnWidth(col, self.COLUMN_WIDTH)

        self.view.resize(320, 200)
        self.view.show()

    def painted_labels(self):
        """Подписи групп, нарисованные при настоящей перерисовке заголовка."""
        painted = []
        original = self.header._paint_group_header

        def spy(painter, rect, label):
            painted.append(label)
            return original(painter, rect, label)

        self.header._paint_group_header = spy
        try:
            self.header.render(QPixmap(self.header.size()))
        finally:
            self.header._paint_group_header = original
        return sorted(set(painted))

    def scroll_to(self, offset: int):
        self.view.horizontalScrollBar().setValue(offset)
        QApplication.processEvents()


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GroupLabelSurvivesScrollingTest(HeaderCase):
    """BUG-20: подпись месяца пропадала, стоило увести первую колонку группы за край.

    Qt вызывает `paintSection` только для видимых секций, а подпись рисовалась
    исключительно при отрисовке первой колонки группы. Проверяется случай, ради
    которого пункт и заведён: колонки группы на экране, а её начала — нет.
    """

    def test_label_is_drawn_while_the_group_starts_on_screen(self):
        self.scroll_to(0)
        self.assertIn("Январь", self.painted_labels())

    def test_label_survives_its_first_column_leaving_the_screen(self):
        # 900 px = восемь колонок: секция 8 уходит за левый край целиком,
        # а секции 9…11 той же группы видны.
        self.scroll_to(900)
        self.assertLess(self.header.sectionViewportPosition(8), 0)
        self.assertGreaterEqual(self.header.sectionViewportPosition(9), 0)

        self.assertIn("Март", self.painted_labels())

    def test_label_of_a_group_beyond_the_screen_is_not_drawn(self):
        """Обратная сторона: подпись не рисуется для групп, которых не видно."""
        self.scroll_to(900)
        self.assertNotIn("Январь", self.painted_labels())

    def test_visible_part_of_the_group_is_clipped_to_the_viewport(self):
        self.scroll_to(900)
        rect = self.header._visible_group_rect(8, 11, 0)

        self.assertIsNotNone(rect)
        self.assertEqual(0, rect.x())
        self.assertLessEqual(rect.width(), self.header.viewport().width())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ColumnWidthIsDraggableTest(HeaderCase):
    """BUG-10: заголовок был объявлен прозрачным для событий мыши.

    Флаг ставился против hover-артефактов, а отдавал мимо все события сразу —
    вместе с ними исчезла возможность тянуть границы колонок, и ширина
    оставалась такой, какой её угадала эвристика по длине заголовка.
    """

    def drag_border_of_first_column(self, by: int) -> None:
        """Тянет границу между первой и второй колонками, как это делает мышью пользователь."""
        viewport = self.header.viewport()
        x = self.header.sectionViewportPosition(0) + self.header.sectionSize(0)
        y = viewport.height() // 2
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(x, y))
        QTest.mouseMove(viewport, QPoint(x + by, y))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, QPoint(x + by, y))

    def test_pointer_over_the_header_reaches_it(self):
        """Указатель попадает в заголовок, а не сквозь него.

        Проверяется тем же `childAt`, которым Qt выбирает получателя события
        мыши: у виджета с `WA_TransparentForMouseEvents` он возвращает None, и
        до обработчика изменения ширины дело не доходит вовсе.
        """
        self.scroll_to(0)
        point = self.header.mapTo(
            self.view, QPoint(self.header.width() // 2, self.header.height() // 2)
        )

        self.assertIs(self.header.viewport(), self.view.childAt(point))

    def test_dragging_the_border_changes_the_column_width(self):
        """Вторая половина пути: событие дошло — ширина меняется.

        Событие доставляется прямо во viewport заголовка, поэтому сам по себе
        этот тест к `WA_TransparentForMouseEvents` нечувствителен: отбор
        получателя остаётся выше. Он показывает другое — что изменению ширины не
        мешают ни собственная отрисовка секций, ни двухуровневая разметка.
        """
        self.scroll_to(0)
        before = self.header.sectionSize(0)

        self.drag_border_of_first_column(by=60)

        self.assertEqual(before + 60, self.header.sectionSize(0))

    def test_pointer_is_tracked_so_the_resize_cursor_appears(self):
        """Без этого тянуть можно, но курсор у границы не меняется — и не догадаешься."""
        self.assertTrue(self.header.hasMouseTracking())


# --- Модели таблиц ----------------------------------------------------------

class Row:
    """Запись подробной таблицы: точное значение, целые id и год."""

    def __init__(self, id, value, year):
        self.id = id
        self.value = value
        self.year = year


class CountingRow:
    """Запись, считающая каждое обращение к своим полям."""

    reads = 0

    def __init__(self, **fields):
        self.__dict__["_fields"] = fields

    def __getattr__(self, name):
        fields = self.__dict__["_fields"]
        if name not in fields:
            raise AttributeError(name)
        CountingRow.reads += 1
        return fields[name]


def detail_model(rows, headers, attrs):
    model = SQLAlchemyTableModel()
    model.setHeaders(headers)
    model.setColumnAttributes(attrs)
    model.set_source_data(rows)
    return model


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DetailValuesAreFormattedTest(unittest.TestCase):
    """BUG-26: сводная таблица разделяла разряды, подробная показывала `str(value)`.

    Одно и то же число выводилось в двух режимах одного отчёта по-разному, а
    сверяют его с бланком глазами именно в подробном: оттуда удаляют записи.
    """

    def setUp(self):
        self.model = detail_model(
            [Row(id=1234, value=Decimal("1234.567"), year=2025),
             Row(id=2, value=Decimal("1234567"), year=2025)],
            ["ID", "Значение", "Год"],
            ["id", "value", "year"],
        )

    def display(self, row, col):
        return self.model.data(self.model.index(row, col), Qt.ItemDataRole.DisplayRole)

    def test_fractional_value_reads_like_in_the_pivot(self):
        self.assertEqual("1 234,57", self.display(0, 1))

    def test_whole_value_gets_no_decimal_tail(self):
        self.assertEqual("1 234 567", self.display(1, 1))

    def test_year_keeps_its_digits_together(self):
        """Год — не величина: «2 025» не год, а разряды в нём разделять нечего."""
        self.assertEqual("2025", self.display(0, 2))

    def test_identifier_keeps_its_digits_together(self):
        self.assertEqual("1234", self.display(0, 0))

    def test_export_still_gets_the_number_itself(self):
        """Форматирование — только для экрана: в файл уходит само значение (FUNC-2)."""
        self.assertEqual(
            Decimal("1234.567"),
            self.model.data(self.model.index(0, 1), RAW_VALUE_ROLE),
        )


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AlignmentDoesNotReadTheRecordsTest(unittest.TestCase):
    """PERF-7: выравнивание определялось по типу значения в конкретной ячейке.

    То есть при каждой перерисовке для каждой видимой ячейки выполнялся разбор
    пути и цепочка `getattr`. Состав колонки по строкам не меняется, и решать
    это достаточно один раз на загрузку.
    """

    def setUp(self):
        rows = [CountingRow(id=i, value=Decimal("1"), name="АК") for i in range(20)]
        self.model = detail_model(rows, ["ID", "Значение", "Название"],
                                  ["id", "value", "name"])
        CountingRow.reads = 0

    def alignment(self, row, col):
        return self.model.data(self.model.index(row, col),
                               Qt.ItemDataRole.TextAlignmentRole)

    def test_repaint_of_every_cell_touches_no_record(self):
        for row in range(self.model.rowCount()):
            for col in range(self.model.columnCount()):
                self.alignment(row, col)

        self.assertEqual(0, CountingRow.reads)

    def test_numbers_are_still_aligned_to_the_right(self):
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self.assertEqual(right, self.alignment(0, 0))
        self.assertEqual(right, self.alignment(0, 1))

    def test_text_is_still_aligned_to_the_left(self):
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        self.assertEqual(left, self.alignment(0, 2))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SetDataBelongsToQtTest(unittest.TestCase):
    """BUG-12: обе модели переопределяли `setData` своей сигнатурой.

    С `QAbstractItemModel.setData(index, value, role)` у них совпадало только
    имя. Делегат, `QDataWidgetMapper` или включённое редактирование позвали бы
    метод с индексом вместо списка записей.
    """

    def test_detail_model_answers_qts_call(self):
        model = detail_model([Row(id=1, value=Decimal("1"), year=2025)],
                             ["ID", "Значение", "Год"], ["id", "value", "year"])

        accepted = model.setData(model.index(0, 0), "чужое", Qt.ItemDataRole.EditRole)

        self.assertFalse(accepted)
        self.assertEqual(1, model.rowCount())
        self.assertEqual("1", model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole))

    def test_pivot_model_answers_qts_call(self):
        model = PivotDictModel()
        model.set_source_data([{"k": 1}], ["колонка"], ["k"])

        accepted = model.setData(model.index(0, 0), "чужое", Qt.ItemDataRole.EditRole)

        self.assertFalse(accepted)
        self.assertEqual("1", model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DefaultRoleIsDisplayTest(unittest.TestCase):
    """BUG-13: по умолчанию подставлялся сам класс `Qt.ItemDataRole`.

    Не роль, а перечисление целиком: вызов без роли не совпадал ни с одной
    веткой и возвращал None. Скрыто тем, что Qt всегда передаёт роль явно.
    """

    def test_detail_model_shows_the_value(self):
        model = detail_model([Row(id=7, value=Decimal("1"), year=2025)],
                             ["ID", "Значение", "Год"], ["id", "value", "year"])

        self.assertEqual("7", model.data(model.index(0, 0)))

    def test_pivot_model_shows_the_value(self):
        model = PivotDictModel()
        model.set_source_data([{"k": 1}], ["колонка"], ["k"])

        self.assertEqual("1", model.data(model.index(0, 0)))

    def test_header_data_returns_the_caption(self):
        model = PivotDictModel()
        model.set_source_data([{"k": 1}], ["колонка"], ["k"])

        self.assertEqual("колонка", model.headerData(0, Qt.Orientation.Horizontal))


# --- Перенос длинных подписей заголовка -------------------------------------

class FixedWidthMetrics:
    """Метрики шрифта, где каждая буква ровно 10 пикселей.

    Настоящие `QFontMetrics` зависят от шрифта системы, и проверять по ним
    «сколько строк вышло» значило бы проверять шрифт, а не перенос.
    """

    def horizontalAdvance(self, text: str) -> int:
        return 10 * len(text)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WrapHeaderTextTest(unittest.TestCase):
    """Подпись обрезалась по ширине колонки: от названия оставалась середина."""

    metrics = FixedWidthMetrics()

    def wrap(self, text: str, width: int) -> list[str]:
        return wrap_header_text(text, width, self.metrics)

    def test_short_label_stays_one_line(self):
        self.assertEqual(["Свод"], self.wrap("Свод", 200))

    def test_long_label_breaks_between_words(self):
        self.assertEqual(
            ["Акционерное", "общество", "Якутия"],
            self.wrap("Акционерное общество Якутия", 120),
        )

    def test_nothing_is_lost_on_the_way(self):
        text = 'Общество с ограниченной ответственностью "Авиакомпания "Полярные авиалинии"'

        for width in (40, 90, 150, 300, 1000):
            with self.subTest(width=width):
                # Пробелы не в счёт: слишком длинное слово рвётся по буквам,
                # и куски становятся отдельными строками.
                joined = "".join(self.wrap(text, width))
                self.assertEqual("".join(text.split()), "".join(joined.split()))

    def test_every_line_fits_the_width(self):
        text = 'Акционерное общество "Авиакомпания "Якутия"'

        for width in (30, 70, 130, 400):
            with self.subTest(width=width):
                for line in self.wrap(text, width):
                    self.assertLessEqual(self.metrics.horizontalAdvance(line), width, line)

    def test_word_longer_than_the_column_is_split_by_letters(self):
        """Иначе «при любой ширине» не выполняется: такое слово осталось бы обрезанным."""
        lines = self.wrap("Авиакомпания", 50)

        self.assertEqual(["Авиак", "омпан", "ия"], lines)
        self.assertEqual("Авиакомпания", "".join(lines))

    def test_column_without_width_keeps_the_label_whole(self):
        """Ширины ещё нет — рвать не по чему; подпись отдаётся целиком, без зацикливания."""
        self.assertEqual(["Свод"], self.wrap("Свод", 0))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class HeaderShowsTheWholeLabelTest(HeaderCase):
    """Высота шапки идёт за переносом: весь текст виден при любой ширине колонки."""

    LONG = 'Акционерное общество "Авиакомпания "Полярные авиалинии"'

    def set_long_header(self, column: int = 1):
        headers = [f"колонка {i}" for i in range(self.COLUMNS)]
        headers[column] = self.LONG
        keys = [f"k{i}" for i in range(self.COLUMNS)]
        self.model.set_source_data([{k: 1 for k in keys}], headers, keys)
        for col in range(self.COLUMNS):
            self.view.setColumnWidth(col, self.COLUMN_WIDTH)
        QApplication.processEvents()

    def lines_of(self, column: int) -> list[str]:
        width = self.header.sectionSize(column) - 2 * TEXT_MARGIN
        return wrap_header_text(
            self.model.headerData(column, Qt.Orientation.Horizontal),
            width, self.header.fontMetrics(),
        )

    def test_short_labels_leave_the_header_one_line_high(self):
        one_line = self.header.fontMetrics().height() + self.header._group_height

        self.assertLess(self.header.required_height(), 2 * one_line)

    def test_header_grows_to_fit_the_wrapped_label(self):
        self.set_long_header()
        lines = self.lines_of(1)

        self.assertGreater(len(lines), 1)
        self.assertGreaterEqual(
            self.header.height(),
            len(lines) * self.header.fontMetrics().height() + self.header._group_height,
        )

    def test_narrowing_the_column_raises_the_header(self):
        self.set_long_header()
        before = self.header.height()

        self.view.setColumnWidth(1, 40)
        QApplication.processEvents()

        self.assertGreater(self.header.height(), before)
        self.assertGreaterEqual(
            self.header.height(),
            len(self.lines_of(1)) * self.header.fontMetrics().height()
            + self.header._group_height,
        )

    def test_widening_the_column_lowers_the_header_back(self):
        """Шапка не остаётся высокой навсегда: место возвращается таблице."""
        self.set_long_header()
        tall = self.header.height()

        self.view.setColumnWidth(1, 900)
        QApplication.processEvents()

        self.assertLess(self.header.height(), tall)
        self.assertEqual(1, len(self.lines_of(1)))


if __name__ == "__main__":
    unittest.main()
