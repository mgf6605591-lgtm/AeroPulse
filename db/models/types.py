# db/models/types.py
"""Типы колонок, которых нет в SQLite.

SQLite не хранит десятичные числа: у типа `DECIMAL` числовое сродство, и любое
значение кладётся в него как `REAL`, то есть двоичный `float`. Отчётность
приходит в десятичном виде — 5896.29 тыс. ткм, — и после такого преобразования в
базе лежит ближайшее двоичное приближение, а не то число, что стоит в бланке.
Расхождение вылезает при суммировании и в младших разрядах официального отчёта.
"""
from decimal import Decimal

from sqlalchemy import Integer, String
from sqlalchemy.types import TypeDecorator

from db.models.enums import Months

# Номер месяца — порядок объявления в перечислении: январь первый.
_MONTH_TO_NUMBER = {month: number for number, month in enumerate(Months, start=1)}
_NUMBER_TO_MONTH = {number: month for month, number in _MONTH_TO_NUMBER.items()}


class MonthNumber(TypeDecorator):
    """Месяц: в базе — число 1…12, в Python — член `Months`.

    Месяц хранился именем («January»), а имена несравнимы по порядку: SQL мог
    ограничить выборку только по годам, и отбор по месяцу делался перебором уже
    поднятых записей (PERF-1). Номер упорядочен, поэтому весь период уходит в
    запрос одним условием.

    Прикладной код при этом не меняется: он получает и передаёт `Months`.
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, Months):
            return _MONTH_TO_NUMBER[value]
        if isinstance(value, str):
            # Имя месяца — как в прежнем хранении и в данных, приходящих из парсеров.
            return _MONTH_TO_NUMBER[Months[value]]
        number = int(value)
        if number not in _NUMBER_TO_MONTH:
            raise ValueError(f"Номер месяца вне диапазона 1…12: {value!r}")
        return number

    def process_result_value(self, value, dialect) -> Months | None:
        if value is None:
            return None
        if isinstance(value, Months):
            return value
        return _NUMBER_TO_MONTH[int(value)]


class ExactDecimal(TypeDecorator):
    """`Decimal`, который хранится текстом и читается обратно без потерь.

    Текст, а не масштабированное целое: число знаков после запятой в бланках не
    задано, и любой выбранный масштаб пришлось бы округлять — ровно та потеря, от
    которой этот тип и заводится.

    Колонка объявляется как `VARCHAR`, чтобы у неё было текстовое сродство. С
    числовым сродством SQLite молча превратил бы «5896.29» обратно в `REAL` при
    записи, и тип не дал бы ничего.

    Сортировка и суммирование средствами SQL по такой колонке лексикографические;
    приложение и то и другое делает в Python. Когда агрегация переедет в SQL
    (PERF-2), значение потребуется приводить: `CAST(value AS REAL)` для порядка
    величин и точное сложение — по-прежнему в Python.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            # float сюда попадать не должен: он уже потерял точность до вызова.
            value = Decimal(str(value))
        # Формат 'f' — без экспоненты: «1E+3» не прочитается как число ни глазами,
        # ни SQLite при сравнении с числовым литералом.
        return format(value, 'f')

    def process_result_value(self, value, dialect) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
