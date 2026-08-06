"""Импортёр: связи детализации показателей и повторная загрузка того же отчёта."""

import unittest
from decimal import Decimal

from sqlalchemy.orm import sessionmaker

from db.models.entities import Airline, AirlineIndicators, Indicator
from importers.data_importer import DataImporter
from tests.support import MigratedDbCase


def indicator_row(code: str, name: str, value: str) -> dict:
    """Строка показателя в том виде, в каком её отдают парсеры 12-ГА."""
    return {
        "indicator_code": code,
        "indicator_name": name,
        "measure": "тыс. ткм",
        "route_type": "trunk",
        "regularity": "regular",
        "value": Decimal(value),
    }


# Детализация идёт до родителя: в бланке строка 450 стоит выше, но полагаться
# на порядок строк файла нельзя.
DETAIL_BEFORE_PARENT = [
    indicator_row("450пас", "      а) пассажирский", "1.5"),
    indicator_row("450гр", "      б) грузовой (вкл. срочный груз)", "2.5"),
    indicator_row("450пч", "      в) почтовый", "0.5"),
    indicator_row("450", "Выполненный тоннокилометраж", "4.5"),
    indicator_row("965", "Самолето-километры", "100"),
]


class ImportCase(MigratedDbCase):
    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(code="AAA", name="Тестовая АК"))
            session.commit()
            self.airline_id = session.query(Airline).one().id

    def payload(self, indicators, month="March", year=2025) -> dict:
        return {
            "entity_type": "airline",
            "data_type": "airline",
            "entity_id": self.airline_id,
            "airline": {"name": "Тестовая АК", "code": "AAA", "id": self.airline_id},
            "month": month,
            "year": year,
            "indicators": indicators,
        }

    def do_import(self, indicators, **kwargs) -> dict:
        with self.Session() as session:
            return DataImporter._import_airline_data(session, self.payload(indicators, **kwargs))

    def indicators_by_code(self) -> dict:
        with self.Session() as session:
            return {ind.code: ind for ind in session.query(Indicator).all()}


class DetailIndicatorLinkTest(ImportCase):
    """parent_id нужен своду 12-ГА для подраздела «в том числе»."""

    def test_detail_rows_linked_to_parent(self):
        self.do_import(DETAIL_BEFORE_PARENT)

        by_code = self.indicators_by_code()
        for code in ("450пас", "450гр", "450пч"):
            self.assertEqual(by_code["450"].id, by_code[code].parent_id, code)

    def test_ordinary_indicators_have_no_parent(self):
        self.do_import(DETAIL_BEFORE_PARENT)

        by_code = self.indicators_by_code()
        self.assertIsNone(by_code["450"].parent_id)
        self.assertIsNone(by_code["965"].parent_id)

    def test_link_repaired_on_next_import(self):
        """Показатели, загруженные до появления этой логики, чинятся при импорте."""
        self.do_import(DETAIL_BEFORE_PARENT)
        with self.Session() as session:
            session.query(Indicator).filter(Indicator.code == "450пас").one().parent_id = None
            session.commit()

        self.do_import(DETAIL_BEFORE_PARENT)

        by_code = self.indicators_by_code()
        self.assertEqual(by_code["450"].id, by_code["450пас"].parent_id)

    def test_no_parent_row_in_file(self):
        """Детализация без родителя не должна ронять импорт."""
        result = self.do_import([indicator_row("450пас", "      а) пассажирский", "1.5")])

        self.assertTrue(result["success"], result["message"])
        self.assertIsNone(self.indicators_by_code()["450пас"].parent_id)


class ReimportTest(ImportCase):
    def test_reimport_updates_instead_of_duplicating(self):
        self.do_import(DETAIL_BEFORE_PARENT)

        result = self.do_import(DETAIL_BEFORE_PARENT)

        self.assertEqual(0, result["imported"])
        self.assertEqual(len(DETAIL_BEFORE_PARENT), result["updated"])
        with self.Session() as session:
            self.assertEqual(len(DETAIL_BEFORE_PARENT), session.query(AirlineIndicators).count())

    def test_corrected_report_overwrites_value(self):
        self.do_import([indicator_row("965", "Самолето-километры", "100")])

        self.do_import([indicator_row("965", "Самолето-километры", "150")])

        with self.Session() as session:
            self.assertEqual(150.0, float(session.query(AirlineIndicators).one().value))

    def test_other_month_is_separate_row(self):
        self.do_import([indicator_row("965", "Самолето-километры", "100")], month="March")

        self.do_import([indicator_row("965", "Самолето-километры", "120")], month="April")

        with self.Session() as session:
            self.assertEqual(2, session.query(AirlineIndicators).count())


if __name__ == "__main__":
    unittest.main()
