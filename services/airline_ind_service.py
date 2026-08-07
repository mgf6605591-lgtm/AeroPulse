# services/airline_ind_service.py
"""Отчётность авиакомпаний: граница сессии и форма выдачи (ARCH-1, BUG-14).

До сих пор служба состояла из методов, каждый из которых открывал сессию и тут же
делегировал одноимённому методу контроллера — ни границ транзакции, ни правил, ни
собственного смысла. Смысл у неё теперь один и понятный: **сессия не переживает
вызов, и ORM-объекты за её пределы не выходят**. Наружу уходят либо суммы для
свода, либо снимки строк для таблицы.
"""
from typing import Any, Dict, List

from controllers.AirlineIndController import AirlineIndController
from db.database import get_session
from services.detail_rows import DetailRow, from_airline_indicator


class AirlineIndicatorService:

    @classmethod
    def aggregate(cls, filters: Dict) -> List[Any]:
        """Ячейки свода: суммы по группам вместо самих фактов (PERF-2)."""
        with get_session() as session:
            return AirlineIndController.aggregate(session, filters or {})

    @classmethod
    def detail_rows(cls, filters: Dict) -> List[DetailRow]:
        """Строки подробной таблицы — снимками, а не записями ORM (BUG-14)."""
        with get_session() as session:
            if filters:
                records = AirlineIndController.filter_indicators(session, filters)
            else:
                records = AirlineIndController.get_all_indicators(session)
            # Преобразование внутри сессии: после выхода связи уже не подгрузить.
            return [from_airline_indicator(record) for record in records]
