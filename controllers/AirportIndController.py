from typing import List, Dict
from controllers.period_filter import apply_period_filter
from db.models.entities import Airport, AirportIndicators
from sqlalchemy import select
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

