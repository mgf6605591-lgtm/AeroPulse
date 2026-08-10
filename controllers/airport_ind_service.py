# controllers/airport_ind_service.py
"""Отчётность аэропортов: граница сессии и форма выдачи (ARCH-1, BUG-14).

То же, что и у авиакомпаний: служба отвечает за то, чтобы сессия не переживала
вызов, а наружу уходили суммы для свода или снимки строк для таблицы — но не
объекты ORM, у которых за пределами сессии не осталось связей.

О том, почему модуль лежит здесь, а не в `services/`, — см.
[controllers/airline_ind_service.py](controllers/airline_ind_service.py) (ARCH-14).
"""
from typing import Any

from controllers.AirportIndController import AirportIndController
from controllers.detail_rows import DetailRow, from_airport_indicator
from controllers.report_filters import NO_FILTERS, ReportFilters
from db.database import get_session


class AirportIndicatorService:

    @classmethod
    def aggregate(cls, filters: ReportFilters) -> list[Any]:
        """Ячейки свода 15-ГА: суммы по группам вместо самих фактов (PERF-2)."""
        with get_session() as session:
            return AirportIndController.aggregate(session, filters or NO_FILTERS)

    @classmethod
    def detail_rows(cls, filters: ReportFilters) -> list[DetailRow]:
        """Строки подробной таблицы — снимками, а не записями ORM (BUG-14)."""
        with get_session() as session:
            if filters:
                records = AirportIndController.filter_indicators(session, filters)
            else:
                records = AirportIndController.get_all_indicators(session)
            return [from_airport_indicator(record) for record in records]
