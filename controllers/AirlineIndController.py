from typing import Any
from controllers.report_filters import ReportFilters
from controllers.period_filter import apply_period_filter
from db.models.entities import AirlineIndicators, Shipping, Airline, Indicator, Route
from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import joinedload


class AirlineIndController:

    @classmethod
    def get_all_indicators(cls, session) -> list[AirlineIndicators]:
        query = select(AirlineIndicators).options(
            joinedload(AirlineIndicators.indicator),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.airline),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.route)
        )
        result = session.execute(query)
        return result.unique().scalars().all()


    @classmethod
    def aggregate(cls, session, filters: ReportFilters) -> list[Any]:
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

        # Ветки на одиночное значение больше нет: `airline_id` проставлялся
        # ровно тогда, когда в списке был один элемент, и `IN (один)` покрывает
        # этот случай сам (ARCH-5).
        if filters.airline_ids:
            query = query.filter(Shipping.airline_id.in_(filters.airline_ids))

        if filters.indicator_ids:
            query = query.filter(
                AirlineIndicators.indicator_id.in_(filters.indicator_ids)
            )

        if filters.route_types:
            query = query.filter(Route.type.in_(filters.route_types))

        query = apply_period_filter(query, AirlineIndicators, filters)
        return session.execute(query).all()

    @classmethod
    def filter_indicators(cls, session, filters: ReportFilters) -> list[AirlineIndicators]:
        """Фильтрация показателей авиакомпаний с поддержкой диапазона периода."""
        query = select(AirlineIndicators).options(
            joinedload(AirlineIndicators.indicator),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.airline),
            joinedload(AirlineIndicators.shipping).joinedload(Shipping.route)
        )

        if filters.airline_ids or filters.route_types:
            query = query.join(AirlineIndicators.shipping)

        if filters.airline_ids:
            query = query.filter(Shipping.airline_id.in_(filters.airline_ids))

        if filters.indicator_ids:
            query = query.filter(
                AirlineIndicators.indicator_id.in_(filters.indicator_ids)
            )

        query = apply_period_filter(query, AirlineIndicators, filters)

        if filters.route_types:
            query = query.join(Shipping.route).filter(Route.type.in_(filters.route_types))

        return session.execute(query).unique().scalars().all()

