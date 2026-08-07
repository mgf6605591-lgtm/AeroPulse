# services/detail_rows.py
"""Строка подробной таблицы — снимок, а не объект ORM (BUG-14).

Службы отдавали наружу сами записи ORM, а сессия закрывалась на выходе из метода.
Дальше таблица обращалась к `rec.indicator.name`, `rec.shipping.airline.name`,
`rec.shipping.route.type` уже у detached-объектов: работало это исключительно
благодаря `expire_on_commit=False` и точно подобранным `joinedload`. Обращение к
полю, которое забыли туда включить, дало бы `DetachedInstanceError` в рантайме —
ошибку, которую не найдёт ни один статический анализатор.

Здесь поля извлечены заранее, внутри сессии. За её пределы уходит обычный объект
без связи с базой: доставать из него нечего, и «забытого» поля не бывает —
недостающее видно сразу, как отсутствующий атрибут.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from db.models.enums import Months, RouteType, ShippingRegularity


@dataclass(frozen=True)
class DetailRow:
    """Одна запись отчётности в том виде, в каком её показывает таблица.

    `id` нужен для удаления: пользователь удаляет строки именно из этого режима.
    Перечисления оставлены перечислениями — таблица показывает их подпись, а
    выгрузка кладёт её же в ячейку.
    """

    id: int
    entity_name: str
    entity_code: str
    indicator: str
    measure: str
    month: Optional[Months]
    year: Optional[int]
    value: Optional[Decimal]
    # Только для 12-ГА: рейс описывается парой «вид маршрута + регулярность».
    route_type: Optional[RouteType] = None
    regularity: Optional[ShippingRegularity] = None
    # Только для 15-ГА: у аэропорта рейсов нет, зато есть населённый пункт.
    locality: Optional[str] = None


def from_airline_indicator(record) -> DetailRow:
    """Снимок строки 12-ГА. Вызывать только внутри открытой сессии."""
    shipping = record.shipping
    airline = shipping.airline if shipping else None
    route = shipping.route if shipping else None
    indicator = record.indicator
    return DetailRow(
        id=record.id,
        entity_name=(airline.name or "").strip() if airline else "",
        entity_code=(airline.code or "").strip() if airline else "",
        indicator=(indicator.name or "").strip() if indicator else "",
        measure=(indicator.measure or "").strip() if indicator else "",
        month=record.month,
        year=record.year,
        value=record.value,
        route_type=route.type if route else None,
        regularity=route.regularity if route else None,
    )


def from_airport_indicator(record) -> DetailRow:
    """Снимок строки 15-ГА. Вызывать только внутри открытой сессии."""
    airport = record.airport
    indicator = record.indicator
    locality = airport.locality if airport else None
    return DetailRow(
        id=record.id,
        entity_name=(airport.name or "").strip() if airport else "",
        entity_code=(airport.code or "").strip() if airport else "",
        indicator=(indicator.name or "").strip() if indicator else "",
        measure=(indicator.measure or "").strip() if indicator else "",
        month=record.month,
        year=record.year,
        value=record.value,
        locality=(locality.name or "").strip() if locality else "",
    )
