"""Ключи разделов свода — имена членов, а не русские подписи (ARCH-6).

`_norm_route_type` возвращал имя члена (`trunk`), `_norm_regularity` — русскую
подпись (`Регулярные коммерческие`). Подписью же ключевались словари агрегации,
порядок разделов и списки кодов. Правка подписи — скажем, «Не регулярные» на
«Нерегулярные» — рассогласовала бы их **молча**: записи перестали бы попадать в
раздел, и он исчез бы из свода без единой ошибки.

Проверено на коде до правки: с переименованной подписью запись нерегулярных
перевозок пропадала из свода целиком, а прогон оставался почти зелёным — падал
только тест, проверяющий саму подпись на экране.

Ниже закреплено свойство, а не текст: чем бы ни была подписана регулярность,
запись попадает в тот же раздел.
"""

import unittest

from controllers.reports.ga12_pivot import _norm_regularity, _norm_route_type
from db.models.entities import Indicator
from db.models.enums import RouteType, ShippingRegularity
from tests.support import FakeRecord, PivotCase
from utils.constants import GA12_CODES_BY_SECTION, GA12_SECTION_TITLE, REGULARITY_ORDER


class OneConventionForBothNormalisersTest(unittest.TestCase):
    """Оба нормализатора возвращают имя члена перечисления."""

    def test_regularity_gives_the_member_name(self):
        self.assertEqual("regular", _norm_regularity(ShippingRegularity.regular))
        self.assertEqual("irregular", _norm_regularity(ShippingRegularity.irregular))

    def test_route_type_gives_the_member_name(self):
        self.assertEqual("trunk", _norm_route_type(RouteType.trunk))
        self.assertEqual("local", _norm_route_type(RouteType.local))

    def test_both_accept_either_written_form(self):
        """Из базы регулярность может прийти и именем, и подписью."""
        for member in ShippingRegularity:
            self.assertEqual(member.name, _norm_regularity(member.name))
            self.assertEqual(member.name, _norm_regularity(member.value))


class SectionKeysAreNotCaptionsTest(unittest.TestCase):
    """Словари разделов ключуются тем же, что возвращает нормализатор."""

    def test_order_holds_member_names(self):
        self.assertEqual([m.name for m in ShippingRegularity], list(REGULARITY_ORDER))

    def test_no_caption_is_used_as_a_key(self):
        captions = {member.value for member in ShippingRegularity}

        for name, mapping in (("порядок", set(REGULARITY_ORDER)),
                              ("заголовки", set(GA12_SECTION_TITLE)),
                              ("коды", set(GA12_CODES_BY_SECTION))):
            self.assertEqual(set(), mapping & captions, name)

    def test_normaliser_result_is_always_a_key(self):
        """Стык, на котором всё и держится: ключ из данных совпадает с ключом раскладки."""
        for member in ShippingRegularity:
            key = _norm_regularity(member)
            self.assertIn(key, REGULARITY_ORDER, member.name)
            self.assertIn(key, GA12_SECTION_TITLE, member.name)
            self.assertIn(key, GA12_CODES_BY_SECTION, member.name)


class RecordReachesItsSectionTest(PivotCase):
    """Стык, ради которого пункт и заведён.

    Раздел строки свода задаёт код показателя (`965` — регулярные, `965н` —
    нерегулярные), а суммы складываются в словарь под ключом регулярности
    записи. Совпасть эти два ключа обязаны — иначе ячейка окажется пустой при
    имеющихся данных.

    Проверяется свод по маршрутам: именно он и складывает по паре
    «регулярность + показатель». Свод по всем авиакомпаниям регулярностью не
    ключуется вовсе — на нём этот стык не виден.
    """

    CODE = "965н"
    NAME = "Самолето-километры нерегулярные"
    HEADING = "— НЕРЕГУЛЯРНЫЕ КОММЕРЧЕСКИЕ ПЕРЕВОЗКИ —"

    def setUp(self):
        super().setUp()
        with self.Session() as session:
            session.add(Indicator(name=self.NAME, code=self.CODE, measure="тыс.сам.-км"))
            session.commit()

    def build(self, regularity):
        records = [FakeRecord(self.CODE, self.NAME, "January", 2025, 100,
                              regularity=regularity)]
        return self.build_per_airline_by_routes(records)

    def value_of(self, result, name):
        for row in result["rows"]:
            if row.get("indicator") == name:
                return row
        raise AssertionError(f"в своде нет строки «{name}»")

    def filled_cells(self, result, name):
        """Заполненные ячейки строки — без подписи, кода и единицы измерения."""
        row = self.value_of(result, name)
        return {
            key: value for key, value in row.items()
            if key not in ("indicator", "code", "measure") and value
        }

    def test_irregular_section_is_rendered(self):
        headings = [row.get("indicator") for row in self.build("irregular")["rows"]]

        self.assertIn(self.HEADING, headings)

    def test_value_lands_in_the_irregular_row(self):
        """При рассогласовании ключей ячейка была бы пустой при наличии данных."""
        self.assertTrue(self.filled_cells(self.build("irregular"), self.NAME))

    def test_regular_record_does_not_leak_into_the_irregular_row(self):
        """Обратная сторона: регулярная запись в нерегулярный раздел не попадает."""
        self.assertEqual({}, self.filled_cells(self.build("regular"), self.NAME))


if __name__ == "__main__":
    unittest.main()
