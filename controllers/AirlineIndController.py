from typing import List, Dict
from db.models.entities import AirlineIndicators, Shipping, Airline, Indicator, Route
from sqlalchemy import select, and_
from sqlalchemy.orm import joinedload


MONTH_INDEX = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4,
    'May': 5, 'June': 6, 'July': 7, 'August': 8,
    'September': 9, 'October': 10, 'November': 11, 'December': 12,
}


class AirlineIndController:

    @classmethod
    def get_all_indicators(cls, session) -> List[AirlineIndicators]:
        query = select(AirlineIndicators).options(
            joinedload(AirlineIndicators.indicator),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.airline),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.route)
        )
        result = session.execute(query)
        return result.unique().scalars().all()

    @classmethod
    def get_indicator_by_id(cls, session, id: int) -> AirlineIndicators:
        query = select(AirlineIndicators).where(AirlineIndicators.id == id).options(
            joinedload(AirlineIndicators.indicator),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.airline)
        )
        result = session.execute(query)
        return result.unique().scalar_one_or_none()

    @classmethod
    def filter_indicators(cls, session, filters: Dict) -> List[AirlineIndicators]:
        """Фильтрация показателей авиакомпаний с поддержкой диапазона периода."""
        query = select(AirlineIndicators).options(
            joinedload(AirlineIndicators.indicator),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.airline),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.route)
        )

        airline_ids = filters.get("airline_ids")
        airline_id_single = filters.get("airline_id")
        route_types = filters.get("route_types")
        route_type_single = filters.get("route_type")

        need_shipping = bool(airline_ids or airline_id_single or route_types or route_type_single)
        if need_shipping:
            query = query.join(AirlineIndicators.shipping)

        if airline_ids:
            query = query.filter(Shipping.airline_id.in_(list(airline_ids)))
        elif airline_id_single:
            query = query.filter(Shipping.airline_id == int(airline_id_single))

        if filters.get("indicator_ids"):
            query = query.filter(
                AirlineIndicators.indicator_id.in_(list(filters["indicator_ids"]))
            )
        elif filters.get("indicator_id"):
            query = query.filter(AirlineIndicators.indicator_id == int(filters["indicator_id"]))

        # Диапазон периода: ограничиваем SQL по годам, точную фильтрацию по месяцу — в Python
        if filters.get('period_from') and filters.get('period_to'):
            yf, _ = filters['period_from']
            yt, _ = filters['period_to']
            query = query.filter(
                and_(AirlineIndicators.year >= yf, AirlineIndicators.year <= yt)
            )

        if route_types:
            query = query.join(Shipping.route).filter(Route.type.in_(list(route_types)))
        elif route_type_single:
            query = query.join(Shipping.route).filter(Route.type == route_type_single)

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
