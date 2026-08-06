"""Ведение справочников и модель удаления (FUNC-1, SCH-10, BUG-31).

Главное, что здесь проверяется, — что удаление строки справочника не уносит с собой
отчётность. Пока форм ведения справочников не было, удалять их было нечем, и каскад
оставался безобидным; с появлением кнопки «Удалить» он стал бы действующим.
"""

import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from controllers.filter_controller import FilterController
from db.models.entities import (
    Airline,
    AirlineIndicators,
    Airport,
    AirportIndicators,
    Indicator,
    Locality,
    Route,
    Shipping,
)
from db.models.enums import Months, RouteType, ShippingRegularity
from services.reference_service import ReferenceService
from tests.support import MigratedDbCase
from utils.constants import MODE_AIRLINE, MODE_AIRPORT


class ReferenceCase(MigratedDbCase):
    """Справочники поверх временной БД: сервис работает через get_session."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        for target in (
            "services.reference_service.get_session",
            "controllers.filter_controller.get_session",
        ):
            patcher = patch(target, self.Session)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed_minimum(self):
        """Населённый пункт, аэропорт, авиакомпания и показатель — без отчётности."""
        with self.Session() as session:
            session.add(Locality(id=1, name="Город"))
            session.flush()
            session.add(Airport(id=1, code="XXX", name="Аэропорт", locality_id=1))
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.add(Indicator(id=1, name="Налет часов", code="356", measure="час."))
            session.commit()

    def add_airport_report(self):
        with self.Session() as session:
            session.add(AirportIndicators(
                indicator_id=1, airport_id=1, month=Months.January,
                year=2025, value=Decimal("10"),
            ))
            session.commit()

    def add_airline_report(self):
        with self.Session() as session:
            session.add(Route(id=1, type=RouteType.trunk, regularity=ShippingRegularity.regular))
            session.flush()
            session.add(Shipping(id=1, route_id=1, airline_id=1))
            session.flush()
            session.add(AirlineIndicators(
                indicator_id=1, shipping_id=1, month=Months.January,
                year=2025, value=Decimal("10"),
            ))
            session.commit()


class DeletionModelTest(ReferenceCase):
    """Два сценария вместо одного каскада (SCH-10)."""

    def setUp(self):
        super().setUp()
        self.seed_minimum()

    def test_airport_without_reports_is_deleted(self):
        result = ReferenceService.delete("airport", 1)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([], ReferenceService.list_rows("airport"))

    def test_airport_with_reports_is_not_deleted(self):
        self.add_airport_report()
        result = ReferenceService.delete("airport", 1)
        self.assertFalse(result["success"])
        self.assertEqual(1, len(ReferenceService.list_rows("airport")))

    def test_reports_survive_a_refused_deletion(self):
        """Смысл запрета: отчётность на месте, а не «удалилось наполовину»."""
        self.add_airport_report()
        ReferenceService.delete("airport", 1)
        with self.Session() as session:
            self.assertEqual(1, session.query(AirportIndicators).count())

    def test_airline_with_reports_is_not_deleted(self):
        self.add_airline_report()
        result = ReferenceService.delete("airline", 1)
        self.assertFalse(result["success"])
        with self.Session() as session:
            self.assertEqual(1, session.query(AirlineIndicators).count())

    def test_locality_with_airports_is_not_deleted(self):
        result = ReferenceService.delete("locality", 1)
        self.assertFalse(result["success"])

    def test_refusal_explains_the_way_out(self):
        """BUG-31: пользователь видит объяснение, а не текст SQLAlchemy."""
        self.add_airport_report()
        message = ReferenceService.delete("airport", 1)["message"]
        self.assertIn("недействующ", message)
        self.assertNotIn("IntegrityError", message)
        self.assertNotIn("FOREIGN KEY", message)

    def test_usage_count_is_reported(self):
        self.add_airport_report()
        row = ReferenceService.list_rows("airport")[0]
        self.assertEqual(1, row["usage"])


class ActiveFlagTest(ReferenceCase):
    """Вывод из работы: запись уходит из списков, данные остаются."""

    def setUp(self):
        super().setUp()
        self.seed_minimum()
        self.add_airport_report()
        self.add_airline_report()

    def test_inactive_airport_disappears_from_filters(self):
        controller = FilterController()
        self.assertEqual(2, len(controller.load_entities(MODE_AIRPORT)))  # «Все» + аэропорт

        ReferenceService.set_active("airport", 1, False)

        controller = FilterController()
        self.assertEqual([(None, "Все")], controller.load_entities(MODE_AIRPORT))

    def test_inactive_airline_disappears_from_filters(self):
        ReferenceService.set_active("airline", 1, False)
        controller = FilterController()
        self.assertEqual([(None, "Все")], controller.load_entities(MODE_AIRLINE))

    def test_reports_are_kept_when_deactivated(self):
        ReferenceService.set_active("airport", 1, False)
        with self.Session() as session:
            self.assertEqual(1, session.query(AirportIndicators).count())
            self.assertIsNotNone(session.get(Airport, 1))

    def test_can_be_returned_to_service(self):
        ReferenceService.set_active("airport", 1, False)
        ReferenceService.set_active("airport", 1, True)
        controller = FilterController()
        self.assertEqual(2, len(controller.load_entities(MODE_AIRPORT)))


class CrudTest(ReferenceCase):
    """Создание и правка — то, ради чего справочники и заводились."""

    def test_locality_and_airport_can_be_created(self):
        created = ReferenceService.create("locality", {"name": "Якутск"})
        self.assertTrue(created["success"], created["message"])

        locality_id = ReferenceService.list_rows("locality")[0]["id"]
        result = ReferenceService.create(
            "airport", {"code": "YKS", "name": "Якутск", "locality_id": locality_id}
        )
        self.assertTrue(result["success"], result["message"])

        rows = ReferenceService.list_rows("airport")
        self.assertEqual(1, len(rows))
        # В таблице показывается название пункта, а не его идентификатор.
        self.assertEqual("Якутск", rows[0]["locality_id"])

    def test_new_records_are_active(self):
        ReferenceService.create("locality", {"name": "Город"})
        lid = ReferenceService.list_rows("locality")[0]["id"]
        ReferenceService.create("airport", {"code": "XXX", "name": "А", "locality_id": lid})
        self.assertTrue(ReferenceService.list_rows("airport")[0]["is_active"])

    def test_duplicate_code_is_refused_readably(self):
        self.seed_minimum()
        result = ReferenceService.create(
            "airline", {"code": "AAA", "name": "Другая АК"}
        )
        self.assertFalse(result["success"])
        self.assertIn("уже есть", result["message"])

    def test_required_field_is_checked_before_the_database(self):
        result = ReferenceService.create("locality", {"name": "   "})
        self.assertFalse(result["success"])
        self.assertIn("Не заполнено", result["message"])

    def test_too_long_value_is_refused(self):
        """SQLite длины не проверяет, поэтому это делает прикладной код (ср. SCH-6)."""
        result = ReferenceService.create("locality", {"name": "Я" * 60})
        self.assertFalse(result["success"])
        self.assertIn("не больше 50", result["message"])

    def test_record_can_be_renamed(self):
        self.seed_minimum()
        result = ReferenceService.update("airline", 1, {"code": "BBB", "name": "Новая АК"})
        self.assertTrue(result["success"], result["message"])
        row = ReferenceService.list_rows("airline")[0]
        self.assertEqual("BBB", row["code"])
        self.assertEqual("Новая АК", row["name"])

    def test_editor_gets_reference_ids_not_labels(self):
        self.seed_minimum()
        values = ReferenceService.raw_values("airport", 1)
        self.assertEqual(1, values["locality_id"])

    def test_indicator_cannot_be_its_own_parent(self):
        self.seed_minimum()
        choices = ReferenceService.choices("indicator", exclude_id=1)
        self.assertEqual([], choices)

    def test_reference_to_another_directory_is_not_excluded(self):
        """Аэропорт №1 ссылается на населённый пункт №1 — совпадение id ничего не значит.

        Редактор вычёркивал текущую запись из любого поля-ссылки, а не только из
        ссылки на свой же справочник, и населённый пункт аэропорта пропадал из списка.
        """
        self.seed_minimum()
        self.assertEqual([(1, "Город")], ReferenceService.choices("locality"))


class PluralTest(unittest.TestCase):
    """Согласование с числом: «1 отчётная строка», а не «1 отчётных строк»."""

    FORMS = ("отчётная строка", "отчётные строки", "отчётных строк")

    def test_agreement(self):
        from services.reference_service import plural

        cases = {1: 0, 2: 1, 4: 1, 5: 2, 11: 2, 14: 2, 21: 0, 22: 1, 25: 2, 101: 0, 111: 2}
        for count, form_index in cases.items():
            with self.subTest(count=count):
                self.assertEqual(self.FORMS[form_index], plural(count, self.FORMS))


if __name__ == "__main__":
    unittest.main()
