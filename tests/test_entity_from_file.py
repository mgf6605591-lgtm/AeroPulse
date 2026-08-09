"""Импорт 12-ГА с выбором «предприятие из файла».

Годовой комплект приходит одной папкой на несколько авиакомпаний сразу
(`0615106_12_12_2269_2025_1.xml` … `_2812_2025_12.xml`), и каждый файл называет
своё предприятие в титуле. Указывать его в диалоге было единственным способом
загрузить такой комплект: тридцать шесть файлов пришлось бы разложить по трём
папкам и провести тремя заходами.

Проверяется то, на чём это ломается молча:

* **название** — в отчёте оно уставное («Акционерное общество "Авиакомпания
  "АЛРОСА"»), в справочнике короткое («АО Авиакомпания АЛРОСА»). Посимвольное
  сравнение завело бы вторую запись, и отчётность одной авиакомпании разошлась
  бы по двум строкам свода;
* **период** — год и месяц стоят в хвосте имени файла без ведущего нуля;
* **пополнение справочника** — заведённая запись должна быть названа в отчёте об
  импорте и не должна оставаться после отказа.

Файлы отчётов собираются здесь по описанию формы (`f12.xml`), а не выгружаются
из парсера: фикстура, выведенная из разбираемого кода, подтверждает только себя.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sqlalchemy.orm import sessionmaker

from db.models.entities import Airline, AirlineIndicators
from importers.data_importer import DataImporter
from parsers.xml_parser import XMLParser
from tests.support import MigratedDbCase
from utils.entity_codes import CODE_LENGTH, unique_entity_code
from utils.entity_names import normalized_entity_name, same_entity_name

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except ImportError:  # PyQt6 отсутствует — проверки Qt пропускаются
    HAS_QT = False

_app = None


def setUpModule():
    global _app
    if HAS_QT:
        _app = QApplication.instance() or QApplication([])

# Названия из настоящего комплекта: слева — как в отчёте, справа — как в
# справочнике рабочей базы.
ALROSA_IN_REPORT = 'Акционерное общество "Авиакомпания "АЛРОСА"'
ALROSA_IN_REGISTER = "АО Авиакомпания АЛРОСА"
YAKUTIA_IN_REPORT = 'Акционерное общество "Авиакомпания "Якутия"'
YAKUTIA_IN_REGISTER = "АО Авиакомпания Якутия"
POLAR_IN_REPORT = 'Акционерное общество "Авиакомпания "Полярные авиалинии"'

# Строки бланка 12-ГА в кодах f12.xml: номер строки → её значение по графам.
# Строка 2 — «Самолето-километры» регулярных перевозок, строка 5 — «Перевезено
# пассажиров», строка 17 — «Самолето-километры» нерегулярных.
GA12_XML_ROWS = (2, 5, 17)

# Графы отчёта: 4 и 5 — международные (в базе складываются), 6 — внутренние,
# 7 — местные, 8 — субсидируемые. Графа 9 — контрольное «итого», в базу не идёт.
GA12_XML_COLS = (4, 5, 6, 7, 8)


def ga12_cell(row: int, col: int) -> int:
    """Своё число в каждой ячейке: перепутанные строки и графы видно сразу."""
    return row * 100 + col


def make_ga12_xml(path, *, name=ALROSA_IN_REPORT, okpo="2269",
                  year="2025", period="1", rows=GA12_XML_ROWS):
    """Файл отчёта 12-ГА. year/period=None — соответствующий атрибут не пишется."""
    attrs = ['code="61510601"', 'OKUD="0615106"', 'form="12"', 'shifr="12-ГА"']
    if year is not None:
        attrs.append(f'year="{year}"')
    if period is not None:
        attrs.append(f'period="{period}"')

    title = []
    if okpo is not None:
        title.append(f'<item name="okpo" value="{okpo}" />')
    if name is not None:
        title.append(f'<item name="name" value="{escape(name)}" />')

    body = []
    for row in rows:
        cols = "".join(
            f'<col code="{col}">{ga12_cell(row, col)}</col>' for col in GA12_XML_COLS
        )
        body.append(f'<row code="{row}">{cols}</row>')

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<report {" ".join(attrs)}>\n'
            f'  <title>{"".join(title)}</title>\n'
            f'  <sections><section code="1">{"".join(body)}</section></sections>\n'
            "</report>\n"
        )
    return path


def escape(value: str) -> str:
    """Кавычки в атрибуте XML — так их пишет и сама выгрузка."""
    return value.replace('"', "&quot;")


class EntityNameMatchingTest(unittest.TestCase):
    """Уставное название против короткого: на этом заводился бы двойник."""

    def test_the_charter_name_and_the_register_name_are_one_airline(self):
        self.assertTrue(same_entity_name(ALROSA_IN_REPORT, ALROSA_IN_REGISTER))

    def test_quotes_and_case_do_not_matter(self):
        self.assertTrue(same_entity_name('ОАО «Авиакомпания "Якутия"', "оао авиакомпания якутия"))

    def test_spelled_out_legal_forms_become_abbreviations(self):
        self.assertEqual("фкп аэропорты севера", normalized_entity_name(
            'Федеральное казённое предприятие "Аэропорты Севера"'
        ))
        self.assertEqual("ооо полет", normalized_entity_name(
            "Общество с ограниченной ответственностью «Полёт»"
        ))

    def test_a_longer_legal_form_is_not_cut_down_to_a_shorter_one(self):
        """Иначе «закрытое акционерное общество» стало бы «закрытое ао»."""
        self.assertEqual("зао полет", normalized_entity_name('Закрытое акционерное общество "Полет"'))

    def test_different_airlines_stay_different(self):
        self.assertFalse(same_entity_name(ALROSA_IN_REPORT, YAKUTIA_IN_REGISTER))

    def test_words_of_the_name_are_not_dropped(self):
        """«АО Авиакомпания Якутия» и «АО Якутия» — разные юридические лица."""
        self.assertFalse(same_entity_name(YAKUTIA_IN_REGISTER, "АО Якутия"))

    def test_nothing_matches_an_empty_name(self):
        for value in ("", None, "   ", "«»"):
            self.assertFalse(same_entity_name(value, ALROSA_IN_REGISTER), value)
            self.assertFalse(same_entity_name(value, value), value)


class EntityCodeFromTheReportTest(unittest.TestCase):
    """Код заводимой авиакомпании: отчёт его называет, аэропортовый бланк — нет."""

    def test_the_code_from_the_report_is_taken_as_is(self):
        self.assertEqual("2542", unique_entity_code(POLAR_IN_REPORT, set(), preferred="2542"))

    def test_a_taken_code_is_not_handed_out_twice(self):
        code = unique_entity_code(POLAR_IN_REPORT, {"2542"}, preferred="2542")

        self.assertNotEqual("2542", code)
        self.assertLessEqual(len(code), CODE_LENGTH)

    def test_a_code_that_does_not_fit_the_column_is_not_cut_short(self):
        """Обрезанный ОКПО — это другое число, а не код предприятия из отчёта."""
        code = unique_entity_code("Аэрофлот", set(), preferred="1267573")

        self.assertNotIn("12675", code)

    def test_without_a_code_the_name_still_gives_one(self):
        self.assertTrue(unique_entity_code("Полярные авиалинии", set(), preferred=None))


class Ga12XmlNamesItsAirlineTest(unittest.TestCase):
    """Титул отчёта: название предприятия и его код."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name

    def parse(self, file_name="0615106_12_12_2269_2025_1.xml", **kwargs):
        path = make_ga12_xml(os.path.join(self.directory, file_name), **kwargs)
        return XMLParser.parse_file(path)

    def test_the_airline_is_taken_from_the_title(self):
        self.assertEqual(ALROSA_IN_REPORT, self.parse()["airline"]["name"])

    def test_the_code_is_taken_from_the_title(self):
        """`okpo` титула — код предприятия выгрузки, четыре цифры."""
        self.assertEqual("2269", self.parse()["airline"]["code"])

    def test_the_chosen_airline_wins_over_the_one_in_the_file(self):
        path = make_ga12_xml(os.path.join(self.directory, "report.xml"))
        data = XMLParser.parse_file(path, entity_name=ALROSA_IN_REGISTER, entity_id=7)

        self.assertEqual(ALROSA_IN_REGISTER, data["airline"]["name"])
        self.assertEqual(7, data["airline"]["id"])

    def test_the_period_comes_from_the_attributes(self):
        data = self.parse(year="2025", period="7")

        self.assertEqual(("July", 2025), (data["month"], data["year"]))

    def test_the_file_name_supplies_the_period_when_the_attributes_do_not(self):
        """Год и месяц — последние два числа имени, у месяца ведущего нуля нет."""
        data = self.parse("0615106_12_12_2269_2025_9.xml", year=None, period=None)

        self.assertEqual(("September", 2025), (data["month"], data["year"]))

    def test_an_unreadable_period_stays_unknown(self):
        """Заглушки «январь 2025» здесь нет: решение принимает вызывающий (DATA-2)."""
        data = self.parse("report.xml", year=None, period=None)

        self.assertEqual((None, None), (data["month"], data["year"]))


class AirlineFromTheFileTest(MigratedDbCase):
    """Запись импорта, когда предприятие в диалоге не выбрано."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name
        with self.Session() as session:
            session.add(Airline(id=1, code="6R", name=ALROSA_IN_REGISTER))
            session.add(Airline(id=2, code="664", name=YAKUTIA_IN_REGISTER))
            session.commit()

    def do_import(self, file_name="0615106_12_12_2269_2025_1.xml", **kwargs) -> dict:
        path = make_ga12_xml(os.path.join(self.directory, file_name), **kwargs)
        data = XMLParser.parse_file(path)
        data["source_file"] = file_name
        with self.Session() as session:
            return DataImporter._import_airline_data(session, data)

    def airlines(self) -> dict:
        with self.Session() as session:
            return {airline.name: airline for airline in session.query(Airline).all()}

    def rows_of(self, airline_name: str) -> int:
        with self.Session() as session:
            airline = session.query(Airline).filter(Airline.name == airline_name).one()
            return (
                session.query(AirlineIndicators)
                .join(AirlineIndicators.shipping)
                .filter_by(airline_id=airline.id)
                .count()
            )

    def test_the_report_goes_into_the_airline_already_in_the_register(self):
        self.assertTrue(self.do_import()["success"])

        self.assertEqual({ALROSA_IN_REGISTER, YAKUTIA_IN_REGISTER}, set(self.airlines()))
        self.assertTrue(self.rows_of(ALROSA_IN_REGISTER))

    def test_a_second_record_for_the_same_airline_is_not_created(self):
        """Двойник развёл бы отчётность одной авиакомпании по двум строкам свода."""
        self.do_import()
        self.do_import(name=YAKUTIA_IN_REPORT, okpo="2812")

        self.assertEqual(2, len(self.airlines()))

    def test_an_unknown_airline_is_entered_with_the_code_from_the_file(self):
        result = self.do_import(name=POLAR_IN_REPORT, okpo="2542")

        self.assertTrue(result["success"])
        entered = self.airlines()[POLAR_IN_REPORT]
        self.assertEqual("2542", entered.code)

    def test_the_entered_airline_is_named_in_the_report(self):
        """Импорт пополняет справочник — узнавать об этом задним числом нельзя."""
        result = self.do_import(name=POLAR_IN_REPORT, okpo="2542")

        self.assertEqual([POLAR_IN_REPORT], result["created_entities"])
        self.assertIn("Полярные авиалинии", result["message"])
        self.assertIn("авиакомпаний", result["message"])

    def test_a_file_without_readable_rows_leaves_the_register_alone(self):
        """Отказ не должен оставлять запись из файла, который в базу не попал."""
        result = self.do_import(name=POLAR_IN_REPORT, okpo="2542", rows=())

        self.assertFalse(result["success"])
        self.assertNotIn(POLAR_IN_REPORT, self.airlines())

    def test_a_file_that_names_no_airline_is_refused(self):
        result = self.do_import(name=None, okpo=None)

        self.assertFalse(result["success"])
        self.assertIn("не названа", result["message"])
        self.assertEqual(2, len(self.airlines()))

    def test_the_chosen_airline_still_wins_over_the_file(self):
        """Выбор в диалоге остаётся выбором: из файла берётся только незаполненное."""
        path = make_ga12_xml(os.path.join(self.directory, "report.xml"), name=POLAR_IN_REPORT)
        data = XMLParser.parse_file(path, entity_id=2)
        with self.Session() as session:
            result = DataImporter._import_airline_data(session, data)

        self.assertTrue(result["success"])
        self.assertEqual({ALROSA_IN_REGISTER, YAKUTIA_IN_REGISTER}, set(self.airlines()))
        self.assertTrue(self.rows_of(YAKUTIA_IN_REGISTER))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class TheDialogOffersTheFileTest(unittest.TestCase):
    """Пункт «из файла» в списке предприятий — он и включает всё остальное."""

    def entities(self, entity_type: str):
        """Список диалога так, как его заполняет главное окно.

        Окно поднимается без своего `__init__`: заполнять его вкладками и
        таблицами значило бы поднимать базу ради одного списка.
        """
        from PyQt6.QtWidgets import QComboBox, QMainWindow

        from forms.mainWin import MainWindow

        window = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)

        combo = QComboBox()
        self.addCleanup(combo.deleteLater)
        with patch("forms.mainWin.ImportService.get_airlines", return_value=[(1, "АК")]), \
             patch("forms.mainWin.ImportService.get_airports", return_value=[(1, "АП")]):
            window.refresh_entities(entity_type, combo)
        return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]

    def test_airlines_open_with_the_file(self):
        """Комплект 12-ГА на несколько авиакомпаний иначе не загрузить одним заходом."""
        from forms.widgets.import_dialog import ENTITY_FROM_FILE

        first_text, first_data = self.entities("airline")[0]

        self.assertEqual(ENTITY_FROM_FILE, first_data)
        self.assertIn("из файла", first_text)

    def test_airports_keep_the_file_too(self):
        from forms.widgets.import_dialog import ENTITY_FROM_FILE

        self.assertEqual(ENTITY_FROM_FILE, self.entities("airport")[0][1])

    def test_the_register_still_follows_the_file(self):
        self.assertEqual(("АК", 1), self.entities("airline")[1])
        self.assertEqual(("АП", 1), self.entities("airport")[1])


if __name__ == "__main__":
    unittest.main()
