from typing import Any, List, Dict
from controllers.period_filter import apply_period_filter
from db.models.entities import AirlineIndicators, Shipping, Airline, Indicator, Route
from sqlalchemy import Float, cast, func, select
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
    def aggregate(cls, session, filters: Dict) -> List[Any]:
        """Ячейки свода одним запросом: суммы по группам (PERF-2).

        Гранула — самая мелкая из нужных построителям: раздел бланка, показатель,
        период, предприятие и вид сообщения. Все своды по авиакомпаниям собираются
        из неё, каждый по своим колонкам, поэтому запрос один на всех.

        Прежде поднимались сами факты — все до одного — и складывались в Python:
        расход памяти был линеен по числу записей, а не по размеру таблицы на
        экране, и повторялся при каждом изменении фильтра.

        Складывает база, то есть двоичными числами, а не `Decimal`. SQLite
        суммирует компенсированно (Кэхэн—Бабушка): там, где наивное сложение
        `float` даёт 0.0, он возвращает точный ответ, а свод и без того
        показывается с двумя знаками. Хранение остаётся точным — в подробной
        таблице и в выгрузке значение по-прежнему `Decimal` (BUG-4).
        """
        query = (
            select(
                Route.regularity.label("regularity"),
                Route.type.label("route_type"),
                Airline.id.label("airline_id"),
                Airline.name.label("airline_name"),
                Indicator.id.label("indicator_id"),
                Indicator.code.label("indicator_code"),
                Indicator.name.label("indicator_name"),
                Indicator.measure.label("measure"),
                AirlineIndicators.year.label("year"),
                AirlineIndicators.month.label("month"),
                func.sum(cast(AirlineIndicators.value, Float)).label("total"),
                func.count().label("records"),
            )
            .join(Shipping, AirlineIndicators.shipping_id == Shipping.id)
            .join(Route, Shipping.route_id == Route.id)
            .join(Airline, Shipping.airline_id == Airline.id)
            .join(Indicator, AirlineIndicators.indicator_id == Indicator.id)
            .group_by(
                Route.regularity, Route.type, Airline.id, Airline.name,
                Indicator.id, Indicator.code, Indicator.name, Indicator.measure,
                AirlineIndicators.year, AirlineIndicators.month,
            )
        )

        airline_ids = filters.get("airline_ids")
        if airline_ids:
            query = query.filter(Shipping.airline_id.in_(list(airline_ids)))
        elif filters.get("airline_id"):
            query = query.filter(Shipping.airline_id == int(filters["airline_id"]))

        if filters.get("indicator_ids"):
            query = query.filter(
                AirlineIndicators.indicator_id.in_(list(filters["indicator_ids"]))
            )
        elif filters.get("indicator_id"):
            query = query.filter(AirlineIndicators.indicator_id == int(filters["indicator_id"]))

        route_types = filters.get("route_types")
        if route_types:
            query = query.filter(Route.type.in_(list(route_types)))
        elif filters.get("route_type"):
            query = query.filter(Route.type == filters["route_type"])

        query = apply_period_filter(query, AirlineIndicators, filters)
        return session.execute(query).all()

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

