"""Значения отчётности хранятся точно, а не двоичным float (BUG-4).

Колонка `value` объявлена десятичной, но у типа `DECIMAL` в SQLite числовое
сродство: значение ложилось как `REAL`. Импортёр вдобавок сам приводил `Decimal`
к `float` прямо перед записью, обесценивая разбор — парсеры аккуратно строят
`Decimal` из текста бланка.

Ошибка не видна на одном числе: 140.62 и его двоичное приближение печатаются
одинаково. Она копится при суммировании и вылезает в младших разрядах
официального отчёта, а в подробной таблице — представлениями вида
12345.670000000000072759576141834259033203125 (BUG-26).
"""

import unittest
from decimal import Decimal

from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from db.migrator import _config, upgrade_to_head
from db.models.entities import Airline, AirlineIndicators
from db.models.types import ExactDecimal
from importers.data_importer import DataImporter
from tests.support import MigratedDbCase, TempDbCase, db_url, scalar

# Число из настоящего бланка: 140.62 тонн перевезённых грузов. Двоичным float
# оно не представимо, поэтому годится как проба на потерю точности.
FROM_THE_BLANK = Decimal("140.62")

# Детализация тоннокилометража за январь: в бланке её сумма в точности равна
# родительской строке. На float это равенство не держится.
TON_DETAIL = (Decimal("5896.29"), Decimal("343.46"), Decimal("49.26"))
TON_PARENT = Decimal("6289.01")


class ExactDecimalTypeTest(unittest.TestCase):
    """Сам тип: во что превращается значение по дороге в базу и обратно."""

    def setUp(self):
        self.type = ExactDecimal()

    def bind(self, value):
        return self.type.process_bind_param(value, None)

    def result(self, value):
        return self.type.process_result_value(value, None)

    def test_decimal_survives_the_round_trip(self):
        self.assertEqual(FROM_THE_BLANK, self.result(self.bind(FROM_THE_BLANK)))

    def test_stored_as_plain_text_without_exponent(self):
        """«1E+3» не прочитается как число ни глазами, ни SQLite."""
        self.assertEqual("1000", self.bind(Decimal("1E+3")))
        self.assertEqual("0.000001", self.bind(Decimal("1E-6")))

    def test_scale_of_the_blank_is_kept(self):
        self.assertEqual("452.00", self.bind(Decimal("452.00")))

    def test_none_stays_none(self):
        self.assertIsNone(self.bind(None))
        self.assertIsNone(self.result(None))


class StoredValueTest(MigratedDbCase):
    """Запись и чтение через импортёр на настоящей схеме."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(Airline(id=1, code="AAA", name="Тестовая АК"))
            session.commit()

    def payload(self, rows):
        return {
            "entity_type": "airline",
            "data_type": "airline",
            "entity_id": 1,
            "airline": {"name": "Тестовая АК", "code": "AAA", "id": 1},
            "month": "January",
            "year": 2025,
            "indicators": [
                {
                    "indicator_code": code,
                    "indicator_name": name,
                    "measure": "тонн",
                    "route_type": "local",
                    "regularity": "regular",
                    "value": value,
                }
                for code, name, value in rows
            ],
        }

    def do_import(self, rows):
        with self.Session() as session:
            result = DataImporter._import_airline_data(session, self.payload(rows))
            session.commit()
        self.assertTrue(result["success"], result.get("message"))

    def values_by_code(self):
        with self.Session() as session:
            return {
                r.indicator.code: r.value
                for r in session.query(AirlineIndicators).all()
            }

    def test_value_is_stored_as_text(self):
        """Колонка с числовым сродством вернула бы «140.62» обратно в REAL."""
        self.do_import([("168", "Перевезено грузов", FROM_THE_BLANK)])

        self.assertEqual("text", scalar(self.engine, "SELECT typeof(value) FROM airlineInd"))
        self.assertEqual("140.62", scalar(self.engine, "SELECT value FROM airlineInd"))

    def test_value_reads_back_exactly(self):
        self.do_import([("168", "Перевезено грузов", FROM_THE_BLANK)])

        stored = self.values_by_code()["168"]
        self.assertEqual(FROM_THE_BLANK, stored)
        # Приведение к float даёт другое число — ровно то, что лежало в базе раньше.
        self.assertNotEqual(Decimal(140.62), stored)

    def test_detail_still_sums_up_to_its_parent(self):
        """Равенство из бланка должно пережить запись в базу и чтение из неё."""
        rows = [
            ("450пас", "а) пассажирский", TON_DETAIL[0]),
            ("450гр", "б) грузовой (вкл. срочный груз)", TON_DETAIL[1]),
            ("450пч", "в) почтовый", TON_DETAIL[2]),
            ("450", "Выполненный тоннокилометраж", TON_PARENT),
        ]
        self.do_import(rows)

        stored = self.values_by_code()
        detail = stored["450пас"] + stored["450гр"] + stored["450пч"]
        self.assertEqual(stored["450"], detail)

    def test_long_value_is_not_truncated_on_the_way_in(self):
        """Проба на само приведение в импортёре, а не на тип колонки.

        На числах бланка приведение к `float` обратимо: `str(140.62)` снова даёт
        «140.62», и тип колонки восстановил бы значение. Разрядов больше, чем
        помещается в double, — и восстанавливать уже нечего.
        """
        long_value = Decimal("5896.1234567890123456789")

        self.do_import([("450", "Выполненный тоннокилометраж", long_value)])

        self.assertEqual(long_value, self.values_by_code()["450"])

    def test_float_input_is_not_widened(self):
        """Значение не из парсера переводится через str, а не Decimal(float)."""
        self.do_import([("168", "Перевезено грузов", 140.62)])

        self.assertEqual(FROM_THE_BLANK, self.values_by_code()["168"])


class ValueColumnMigrationTest(TempDbCase):
    """Переезд накопленных значений из REAL в текст."""

    def setUp(self):
        super().setUp()
        # Состояние до ревизии: колонка значений ещё десятичная (то есть REAL).
        command.upgrade(_config(db_url(self.engine)), "b7a4c9f21e05")

    def seed_real_value(self, value: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO airlines (id, code, name) VALUES (1, 'AAA', 'Тестовая АК')"
            ))
            conn.execute(text(
                "INSERT INTO routes (id, type, regularity) VALUES (1, 'trunk', 'regular')"
            ))
            conn.execute(text(
                "INSERT INTO shipping (id, route_id, airline_id) VALUES (1, 1, 1)"
            ))
            conn.execute(text(
                "INSERT INTO indicators (id, name, code, measure) "
                "VALUES (1, 'Перевезено грузов', '168', 'тонн')"
            ))
            conn.execute(
                text(
                    "INSERT INTO airlineInd (id, indicator_id, shipping_id, month, year, value) "
                    "VALUES (1, 1, 1, 'January', 2025, :v)"
                ),
                {"v": value},
            )

    def test_accumulated_values_become_text(self):
        self.seed_real_value(140.62)
        self.assertEqual("real", scalar(self.engine, "SELECT typeof(value) FROM airlineInd"))

        upgrade_to_head(self.engine)

        self.assertEqual("text", scalar(self.engine, "SELECT typeof(value) FROM airlineInd"))

    def test_migration_keeps_the_shortest_representation(self):
        """SQLite отдаёт кратчайшую запись, дающую тот же REAL, — не «140.6200000000000045…»."""
        self.seed_real_value(140.62)

        upgrade_to_head(self.engine)

        self.assertEqual("140.62", scalar(self.engine, "SELECT value FROM airlineInd"))

    def test_value_is_readable_as_decimal_after_migration(self):
        self.seed_real_value(140.62)

        upgrade_to_head(self.engine)

        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with Session() as session:
            self.assertEqual(FROM_THE_BLANK, session.query(AirlineIndicators).one().value)


if __name__ == "__main__":
    unittest.main()
