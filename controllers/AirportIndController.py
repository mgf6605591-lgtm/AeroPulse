from typing import Any, List, Dict
from controllers.period_filter import apply_period_filter
from db.models.entities import Airport, AirportIndicators, Indicator
from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import joinedload


class AirportIndController:

    @classmethod
    def get_all_indicators(cls, session) -> List[AirportIndicators]:
        query = select(AirportIndicators).options(
            joinedload(AirportIndicators.indicator),
            joinedload(AirportIndicators.airport).joinedload(Airport.locality)
        )
        result = session.execute(query)
        return result.unique().scalars().all()


    @classmethod
    def aggregate(cls, session, filters: Dict) -> List[Any]:
        """Ячейки свода 15-ГА одним запросом: сумма по показателю и периоду (PERF-2)."""
        query = (
            select(
                Indicator.code.label("indicator_code"),
                AirportIndicators.year.label("year"),
                AirportIndicators.month.label("month"),
                func.sum(cast(AirportIndicators.value, Float)).label("total"),
                func.count().label("records"),
            )
            .join(Indicator, AirportIndicators.indicator_id == Indicator.id)
            .group_by(Indicator.code, AirportIndicators.year, AirportIndicators.month)
        )

        if filters.get("airport_ids"):
            query = query.filter(AirportIndicators.airport_id.in_(list(filters["airport_ids"])))
        elif filters.get("airport_id"):
            query = query.filter(AirportIndicators.airport_id == int(filters["airport_id"]))

        if filters.get("indicator_ids"):
            query = query.filter(
                AirportIndicators.indicator_id.in_(list(filters["indicator_ids"]))
            )
        elif filters.get("indicator_id"):
            query = query.filter(AirportIndicators.indicator_id == int(filters["indicator_id"]))

        query = apply_period_filter(query, AirportIndicators, filters)
        return session.execute(query).all()

    @classmethod
    def filter_indicators(cls, session, filters: Dict) -> List[AirportIndicators]:
        """Фильтрация показателей аэропортов с поддержкой диапазона периода."""
        query = select(AirportIndicators).options(
            joinedload(AirportIndicators.indicator),
            joinedload(AirportIndicators.airport).joinedload(Airport.locality)
        )

        if filters.get('airport_ids'):
            query = query.filter(AirportIndicators.airport_id.in_(list(filters['airport_ids'])))
        elif filters.get('airport_id'):
            query = query.filter(AirportIndicators.airport_id == int(filters['airport_id']))

        if filters.get('indicator_ids'):
            query = query.filter(
                AirportIndicators.indicator_id.in_(list(filters['indicator_ids']))
            )
        elif filters.get('indicator_id'):
            query = query.filter(AirportIndicators.indicator_id == int(filters['indicator_id']))

        query = apply_period_filter(query, AirportIndicators, filters)

        return session.execute(query).unique().scalars().all()

