# controllers/airline_ind_service.py
"""Отчётность авиакомпаний: граница сессии и форма выдачи (ARCH-1, BUG-14).

До сих пор служба состояла из методов, каждый из которых открывал сессию и тут же
делегировал одноимённому методу контроллера — ни границ транзакции, ни правил, ни
собственного смысла. Смысл у неё теперь один и понятный: **сессия не переживает
вызов, и ORM-объекты за её пределы не выходят**. Наружу уходят либо суммы для
свода, либо снимки строк для таблицы.

Лежит рядом с репозиторием, а не в `services/`, потому что только его и
обёртывает: сессия открывается вокруг вызова `AirlineIndController` и закрывается
на выходе. Пока модуль жил в `services/`, пакеты были замкнуты в кольцо —
`controllers.data_controller` звал его, а он звал `controllers.AirlineIndController`,
— и уровни из этих двух пакетов не строились (ARCH-14).
"""
from typing import Any

from controllers.AirlineIndController import AirlineIndController
from controllers.detail_rows import DetailRow, from_airline_indicator
from controllers.report_filters import NO_FILTERS, ReportFilters
from db.database import get_session


class AirlineIndicatorService:

    @classmethod
    def aggregate(cls, filters: ReportFilters) -> list[Any]:
        """Ячейки свода: суммы по группам вместо самих фактов (PERF-2)."""
        with get_session() as session:
            return AirlineIndController.aggregate(session, filters or NO_FILTERS)

    @classmethod
    def detail_rows(cls, filters: ReportFilters) -> list[DetailRow]:
        """Строки подробной таблицы — снимками, а не записями ORM (BUG-14)."""
        with get_session() as session:
            if filters:
                records = AirlineIndController.filter_indicators(session, filters)
            else:
                records = AirlineIndController.get_all_indicators(session)
            # Преобразование внутри сессии: после выхода связи уже не подгрузить.
            return [from_airline_indicator(record) for record in records]
