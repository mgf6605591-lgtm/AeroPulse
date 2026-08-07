from typing import List, Dict
from controllers.period_filter import apply_period_filter
from db.models.entities import AirlineIndicators, Shipping, Airline, Indicator, Route
from sqlalchemy import select
from sqlalchemy.orm import joinedload


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

        query = apply_period_filter(query, AirlineIndicators, filters)

        if route_types:
            query = query.join(Shipping.route).filter(Route.type.in_(list(route_types)))
        elif route_type_single:
            query = query.join(Shipping.route).filter(Route.type == route_type_single)

        return session.execute(query).unique().scalars().all()

