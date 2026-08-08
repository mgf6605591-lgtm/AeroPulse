"""Длины текстовых полей и объявление моделей (SCH-6, SCH-8).

Объявленные лимиты реальную отчётность не вмещали: название показателя, которое
складывает разбор 15-ГА, доходит до 82 символов при объявленных пятидесяти, код
формы — до 21 при двадцати. SQLite длину VARCHAR не проверяет, поэтому на нём
это ничем себя не выдавало; на PostgreSQL или MSSQL импорт упал бы на первой же
строке.

Проверки идут от того, что порождают разборы бланков, а не от записанных в
реестре чисел: длины пересчитываются из раскладок форм здесь же. Новая строка в
бланке, из-за которой название перестанет помещаться, уронит тест — а не
обнаружится при переносе на другую СУБД.

Ограничения и внешние ключи, пережившие перестройку таблиц миграцией, отдельно
здесь не проверяются: их поведение закреплено в `tests/test_schema.py`, а тот
работает на базе, поднятой миграциями до актуальной версии.
"""

import unittest

from sqlalchemy import String, insert, select
from sqlalchemy.orm import DeclarativeBase

from db.models.entities import Airline, Airport, Base, Indicator, Locality, User
from parsers.f15_xml_parser import (
    F15_COL_TITLES,
    F15_COL_TO_METRIC,
    F15_ROW_TITLES,
    F15_XML_ROW_TO_RC,
)
from tests.support import MigratedDbCase
from utils.ga12_layout import GA12_ROWS


def declared_length(model, column: str) -> int:
    """Объявленная длина колонки — из самой модели, а не из повторённого числа."""
    type_ = model.__table__.columns[column].type
    assert isinstance(type_, String), f"{column} — не строковая колонка"
    return type_.length


def longest(values) -> str:
    return max(values, key=len)


def ga15_indicator_names():
    """Все названия показателей, какие может собрать разбор 15-ГА.

    Разбор склеивает название строки бланка с названием графы через длинное тире
    (`parsers/f15_xml_parser.py`), поэтому длина считается по тому же правилу.
    """
    return [
        f"{row_title} — {column_title}"
        for row_title in F15_ROW_TITLES.values()
        for column_title in F15_COL_TITLES.values()
    ]


def ga15_indicator_codes():
    return [
        f"15ГА-{row_code}-{metric}"
        for row_code in F15_XML_ROW_TO_RC.values()
        for metric in F15_COL_TO_METRIC.values()
    ]


class Ga15FitsTheColumnsTest(unittest.TestCase):
    """Форма 15-ГА — та, из-за которой лимиты и оказались малы."""

    def test_longest_indicator_name_fits(self):
        name = longest(ga15_indicator_names())

        self.assertLessEqual(len(name), declared_length(Indicator, "name"),
                             f"не помещается: {name!r} ({len(name)} символов)")

    def test_longest_indicator_code_fits(self):
        code = longest(ga15_indicator_codes())

        self.assertLessEqual(len(code), declared_length(Indicator, "code"),
                             f"не помещается: {code!r} ({len(code)} символов)")

    def test_the_old_limits_really_were_too_small(self):
        """Прежние пятьдесят и двадцать — чтобы проверка выше не выглядела формальной."""
        self.assertGreater(len(longest(ga15_indicator_names())), 50)
        self.assertGreater(len(longest(ga15_indicator_codes())), 20)


class Ga12FitsTheColumnsTest(unittest.TestCase):
    """Форма 12-ГА: короче, но проверяется тем же правилом."""

    def test_indicator_names_fit(self):
        name = longest([row.name for row in GA12_ROWS])

        self.assertLessEqual(len(name), declared_length(Indicator, "name"))

    def test_indicator_codes_fit(self):
        code = longest([row.code for row in GA12_ROWS])

        self.assertLessEqual(len(code), declared_length(Indicator, "code"))

    def test_measures_fit(self):
        measure = longest([row.measure for row in GA12_ROWS])

        self.assertLessEqual(len(measure), declared_length(Indicator, "measure"))


class NameColumnsAgreeTest(unittest.TestCase):
    """Названия предприятий — поля одного рода, и лимит у них общий."""

    def test_all_name_columns_share_the_limit(self):
        lengths = {
            model.__name__: declared_length(model, "name")
            for model in (Airport, Airline, Locality, Indicator)
        }

        self.assertEqual(1, len(set(lengths.values())), lengths)

    def test_email_holds_the_longest_address_allowed(self):
        """RFC 5321: 64 символа локальной части, точка, 255 доменной."""
        self.assertGreaterEqual(declared_length(User, "email"), 320)


class LongestValuesSurviveTheDatabaseTest(MigratedDbCase):
    """Сквозная проверка: значение предельной длины записывается и читается целиком.

    На SQLite она пройдёт и при неверных лимитах — длину он не проверяет. Смысл
    в другом: тест выполняет ровно то, на чём споткнулась бы строгая СУБД, и
    переносится на неё вместе со схемой.
    """

    def round_trip(self, table, column: str, value: str, **extra):
        with self.engine.begin() as conn:
            conn.execute(insert(table).values(**{column: value}, **extra))
            return conn.execute(select(table.__table__.columns[column])).scalar()

    def test_longest_generated_indicator_name(self):
        name = longest(ga15_indicator_names())

        stored = self.round_trip(Indicator, "name", name, code="15ГА-X", measure="ед.")

        self.assertEqual(name, stored)

    def test_longest_generated_indicator_code(self):
        code = longest(ga15_indicator_codes())

        stored = self.round_trip(Indicator, "code", code, name="Показатель", measure="ед.")

        self.assertEqual(code, stored)

    def test_airport_name_of_the_declared_length(self):
        name = "Международный аэропорт " + "Я" * (declared_length(Airport, "name") - 23)

        with self.engine.begin() as conn:
            conn.execute(insert(Locality).values(id=1, name="Город"))
        stored = self.round_trip(Airport, "name", name, code="ЯКТ", locality_id=1)

        self.assertEqual(name, stored)
        self.assertEqual(declared_length(Airport, "name"), len(stored))


class ModelsUseTheCurrentApiTest(unittest.TestCase):
    """SCH-8: база моделей создавалась вызовом, оставшимся от SQLAlchemy 1.x.

    Модели при этом уже были объявлены через `Mapped[...]` и `mapped_column`.
    Схему замена не меняет — за этим следит сверка метаданных с миграциями
    (`tests/test_migrations.py`), — но объявление перестало быть разнородным.
    """

    def test_base_is_a_declarative_base_subclass(self):
        self.assertTrue(issubclass(Base, DeclarativeBase))

    def test_models_are_mapped_through_it(self):
        self.assertIn("indicators", Base.metadata.tables)
        self.assertIs(Base, Indicator.__mro__[Indicator.__mro__.index(Base)])


if __name__ == "__main__":
    unittest.main()
