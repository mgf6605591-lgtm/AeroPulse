"""Строки подробной таблицы переживают закрытие сессии (BUG-14, ARCH-1).

Службы отдавали наружу сами записи ORM, а сессия закрывалась на выходе из метода.
Дальше таблица обращалась к `rec.indicator.name`, `rec.shipping.airline.name`,
`rec.shipping.route.type` уже у detached-объектов: работало это благодаря
`expire_on_commit=False` и точно подобранным `joinedload`. Поле, которое забыли
туда включить, дало бы `DetachedInstanceError` в рантайме.

Проверка идёт на настоящей базе и с настоящей сессией: подделать здесь нечего —
вопрос ровно в том, что происходит после её закрытия.
"""

import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from db.models.entities import (
    Airline, AirlineIndicators, Airport, AirportIndicators, Indicator, Locality, Route, Shipping
)
from db.models.enums import Months, RouteType, ShippingRegularity
from services.airline_ind_service import AirlineIndicatorService
from services.airport_ind_service import AirportIndicatorService
from services.detail_rows import DetailRow
from tests.support import MigratedDbCase


class DetailRowsCase(MigratedDbCase):
    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add_all([
                Airline(id=1, code="AAA", name="Тестовая АК"),
                Route(id=1, type=RouteType.trunk, regularity=ShippingRegularity.irregular),
                Shipping(id=1, route_id=1, airline_id=1),
                Locality(id=1, name="Город"),
                Airport(id=1, code="XXX", name="Тестовый аэропорт", locality_id=1),
                Indicator(id=1, name="Налет часов", code="356", measure="час."),
            ])
            session.flush()
            session.add(AirlineIndicators(
                id=1, indicator_id=1, shipping_id=1,
                month=Months.March, year=2025, value=Decimal("142.5"),
            ))
            session.add(AirportIndicators(
                id=1, indicator_id=1, airport_id=1,
                month=Months.March, year=2025, value=Decimal("610"),
            ))
            session.commit()

        patcher = patch("services.airline_ind_service.get_session", self.Session)
        patcher.start()
        self.addCleanup(patcher.stop)
        airport_patcher = patch("services.airport_ind_service.get_session", self.Session)
        airport_patcher.start()
        self.addCleanup(airport_patcher.stop)


class AirlineDetailRowsTest(DetailRowsCase):

    def rows(self):
        return AirlineIndicatorService.detail_rows({"airline_id": 1})

    def test_service_returns_snapshots_not_orm(self):
        row = self.rows()[0]

        self.assertIsInstance(row, DetailRow)
        self.assertNotIsInstance(row, AirlineIndicators)

    def test_fields_are_readable_after_the_session_closed(self):
        """Ради этого всё и делалось: связей у объекта больше нет, а поля есть."""
        row = self.rows()[0]

        self.assertEqual("Тестовая АК", row.entity_name)
        self.assertEqual("AAA", row.entity_code)
        self.assertEqual("Налет часов", row.indicator)
        self.assertEqual("час.", row.measure)
        self.assertEqual(Months.March, row.month)
        self.assertEqual(2025, row.year)
        self.assertEqual(Decimal("142.5"), row.value)

    def test_route_is_carried_by_both_of_its_parts(self):
        row = self.rows()[0]

        self.assertEqual(RouteType.trunk, row.route_type)
        self.assertEqual(ShippingRegularity.irregular, row.regularity)

    def test_id_survives_for_deletion(self):
        """Удаляют строки именно отсюда, и удалять нужно по id."""
        self.assertEqual(1, self.rows()[0].id)

    def test_snapshot_does_not_change_with_the_database(self):
        """Снимок — не окно в базу: после правки записи он остаётся прежним."""
        row = self.rows()[0]

        with self.Session() as session:
            session.get(AirlineIndicators, 1).value = Decimal("999")
            session.commit()

        self.assertEqual(Decimal("142.5"), row.value)

    def test_empty_filters_return_everything(self):
        self.assertEqual(1, len(AirlineIndicatorService.detail_rows({})))


class AirportDetailRowsTest(DetailRowsCase):

    def rows(self):
        return AirportIndicatorService.detail_rows({"airport_id": 1})

    def test_locality_is_carried(self):
        row = self.rows()[0]

        self.assertEqual("Тестовый аэропорт", row.entity_name)
        self.assertEqual("Город", row.locality)

    def test_airport_row_has_no_route(self):
        """У 15-ГА рейсов нет: пустые поля рейса — это про форму, а не про потерю."""
        row = self.rows()[0]

        self.assertIsNone(row.route_type)
        self.assertIsNone(row.regularity)


class ServiceKeepsSessionsInsideTest(unittest.TestCase):
    """ARCH-1: у службы одна ответственность, и она видна по составу методов."""

    def test_no_method_returns_orm_records(self):
        """Методы, отдававшие записи ORM наружу, убраны, а не переименованы."""
        for service in (AirlineIndicatorService, AirportIndicatorService):
            with self.subTest(service=service.__name__):
                self.assertFalse(hasattr(service, "filter_indicators"))
                self.assertFalse(hasattr(service, "get_all_indicators"))
                self.assertTrue(hasattr(service, "detail_rows"))
                self.assertTrue(hasattr(service, "aggregate"))


if __name__ == "__main__":
    unittest.main()
