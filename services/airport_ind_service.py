# services/airport_ind_service.py
"""Отчётность аэропортов: граница сессии и форма выдачи (ARCH-1, BUG-14).

То же, что и у авиакомпаний: служба отвечает за то, чтобы сессия не переживала
вызов, а наружу уходили суммы для свода или снимки строк для таблицы — но не
объекты ORM, у которых за пределами сессии не осталось связей.
"""
from typing import Any, List

from controllers.AirportIndController import AirportIndController
from controllers.report_filters import NO_FILTERS, ReportFilters
from db.database import get_session
from services.detail_rows import DetailRow, from_airport_indicator


class AirportIndicatorService:

    @classmethod
    def aggregate(cls, filters: ReportFilters) -> List[Any]:
        """Ячейки свода 15-ГА: суммы по группам вместо самих фактов (PERF-2)."""
        with get_session() as session:
            return AirportIndController.aggregate(session, filters or NO_FILTERS)

    @classmethod
    def detail_rows(cls, filters: ReportFilters) -> List[DetailRow]:
        """Строки подробной таблицы — снимками, а не записями ORM (BUG-14)."""
        with get_session() as session:
            if filters:
                records = AirportIndController.filter_indicators(session, filters)
            else:
                records = AirportIndController.get_all_indicators(session)
            return [from_airport_indicator(record) for record in records]
