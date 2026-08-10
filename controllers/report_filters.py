# controllers/report_filters.py
"""Отбор для отчёта — явными полями, а не словарём (ARCH-5).

Фильтры ехали через весь верхний слой обычным `dict`. Контракт нигде не был
описан и не проверялся: опечатка в ключе не вызывала ошибки — отбор просто молча
не применялся, и отчёт получался не тот, о котором думал пользователь. Это тот
же класс отказов, что и в блоке 2, только на чтении: программа не отказывала и
не спрашивала, а тихо показывала другое.

**Парных ключей больше нет.** В словаре жили `airline_id` и `airline_ids`,
`airport_id`/`airport_ids`, `indicator_id`/`indicator_ids`,
`route_type`/`route_types`: одиночный проставлялся, когда в списке ровно один
элемент. Хранится теперь только список, а одиночное значение выводится — оно и
было производным, просто вычислялось при записи, а читалось в шести местах как
самостоятельное.

Нормализация видов сообщения (`.name` против `.value`) здесь намеренно не
трогается: это отдельный пункт разбора (ARCH-6), и смешивать его с заменой
контракта значило бы менять две вещи одним движением.
"""
from dataclasses import dataclass, replace
from typing import Any
from collections.abc import Sequence

Period = tuple[int, int]


def _only(values: Sequence[Any]) -> Any | None:
    """Единственный элемент последовательности — иначе None."""
    return values[0] if len(values) == 1 else None


@dataclass(frozen=True)
class ReportFilters:
    """Что показывать в отчёте. Пустой набор означает «всё без ограничений»."""

    airline_ids: tuple[int, ...] = ()
    airport_ids: tuple[int, ...] = ()
    indicator_ids: tuple[int, ...] = ()
    # Члены перечисления RouteType, как их отдаёт кнопка фильтра.
    route_types: tuple[Any, ...] = ()
    period_from: Period | None = None
    period_to: Period | None = None
    pivot_table_layout: str | None = None

    # --- производные значения ---------------------------------------------

    @property
    def airline_id(self) -> int | None:
        return _only(self.airline_ids)

    @property
    def airport_id(self) -> int | None:
        return _only(self.airport_ids)

    @property
    def indicator_id(self) -> int | None:
        return _only(self.indicator_ids)

    @property
    def route_type(self) -> Any | None:
        return _only(self.route_types)

    @property
    def entity_id(self) -> int | None:
        """Единственное выбранное предприятие — по нему выбирается вид свода.

        Прежде вызывающий перебирал четыре ключа подряд: `airline_id`,
        `airport_id`, а если их нет — списки длиной один. Все четыре ветки
        отвечали на один вопрос.
        """
        airline = self.airline_id
        return airline if airline is not None else self.airport_id

    @property
    def period(self) -> tuple[Period, Period] | None:
        """Обе границы или None: половина периода периодом не является."""
        if self.period_from is None or self.period_to is None:
            return None
        return self.period_from, self.period_to

    def is_set(self) -> bool:
        """Задано ли хоть что-нибудь."""
        return any((
            self.airline_ids, self.airport_ids, self.indicator_ids,
            self.route_types, self.period, self.pivot_table_layout,
        ))

    def __bool__(self) -> bool:
        # Службы отличают «отбор задан» от «показать всё» проверкой `if filters`,
        # и с заменой словаря это должно означать то же самое.
        return self.is_set()


# Пустой отбор — значение по умолчанию там, где фильтры не переданы вовсе.
NO_FILTERS = ReportFilters()


def with_airline(filters: ReportFilters, airline_id: int) -> ReportFilters:
    """Тот же отбор, суженный до одной авиакомпании."""
    return _replace(filters, airline_ids=(int(airline_id),))


def with_airport(filters: ReportFilters, airport_id: int) -> ReportFilters:
    """Тот же отбор, суженный до одного аэропорта."""
    return _replace(filters, airport_ids=(int(airport_id),))


def _replace(filters: ReportFilters | None, **changes) -> ReportFilters:
    return replace(filters or NO_FILTERS, **changes)
