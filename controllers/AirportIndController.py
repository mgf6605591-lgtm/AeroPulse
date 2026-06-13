from typing import List, Dict
from db.models.entities import Airport, AirportIndicators
from sqlalchemy import select, and_
from sqlalchemy.orm import joinedload


MONTH_INDEX = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4,
    'May': 5, 'June': 6, 'July': 7, 'August': 8,
    'September': 9, 'October': 10, 'November': 11, 'December': 12,
}


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
    def get_indicator_by_id(cls, session, id: int) -> AirportIndicators:
        query = select(AirportIndicators).where(AirportIndicators.id == id).options(
            joinedload(AirportIndicators.indicator),
            joinedload(AirportIndicators.airport).joinedload(Airport.locality)
        )
        result = session.execute(query)
        return result.unique().scalar_one_or_none()

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

        if filters.get('period_from') and filters.get('period_to'):
            yf, _ = filters['period_from']
            yt, _ = filters['period_to']
            query = query.filter(
                and_(AirportIndicators.year >= yf, AirportIndicators.year <= yt)
            )

        result = session.execute(query).unique().scalars().all()

        if filters.get('period_from') and filters.get('period_to'):
            yf, mf = filters['period_from']
            yt, mt = filters['period_to']
            start = yf * 100 + mf
            end = yt * 100 + mt
            filtered = []
            for rec in result:
                m = rec.month.name if hasattr(rec.month, 'name') else str(rec.month)
                m_idx = MONTH_INDEX.get(m, 1)
                key = rec.year * 100 + m_idx
                if start <= key <= end:
                    filtered.append(rec)
            return filtered

        return result

    @classmethod
    def delete_indicator(cls, session, id: int) -> bool:
        indicator = cls.get_indicator_by_id(session, id)
        if indicator:
            session.delete(indicator)
            session.commit()
            return True
        return False
