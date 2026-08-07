# db/models/types.py
"""Типы колонок, которых нет в SQLite.

SQLite не хранит десятичные числа: у типа `DECIMAL` числовое сродство, и любое
значение кладётся в него как `REAL`, то есть двоичный `float`. Отчётность
приходит в десятичном виде — 5896.29 тыс. ткм, — и после такого преобразования в
базе лежит ближайшее двоичное приближение, а не то число, что стоит в бланке.
Расхождение вылезает при суммировании и в младших разрядах официального отчёта.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


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

    def process_bind_param(self, value, dialect) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            # float сюда попадать не должен: он уже потерял точность до вызова.
            value = Decimal(str(value))
        # Формат 'f' — без экспоненты: «1E+3» не прочитается как число ни глазами,
        # ни SQLite при сравнении с числовым литералом.
        return format(value, 'f')

    def process_result_value(self, value, dialect) -> Optional[Decimal]:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
