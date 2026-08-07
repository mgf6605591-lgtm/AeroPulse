# controllers/filter_controller.py
import logging
from typing import Dict, Optional, Tuple, Any
from sqlalchemy import func
from controllers.reference_cache import ReferenceDataCache, reference_cache
from db.database import get_session
from db.models.entities import Airline, Airport, Indicator, AirlineIndicators, AirportIndicators
from utils.constants import MONTHS_LIST, MODE_AIRLINE

log = logging.getLogger(__name__)


class FilterController:
    """Контроллер для управления фильтрами"""

    def __init__(self, cache: Optional[ReferenceDataCache] = None):
        # Кеш общий на приложение: свой у каждого экземпляра означал бы, что сброс
        # после импорта не виден остальным виджетам фильтров (BUG-7, ARCH-7).
        self._cache = cache if cache is not None else reference_cache

    def load_entities(self, mode: int) -> list:
        """Загружает список авиакомпаний или аэропортов (для множественного выбора без пункта «Все»)."""
        cached = self._cache.entities(mode)
        if cached is not None:
            return cached

        try:
            with get_session() as session:
                # Только действующие предприятия. Выведенное из работы уходит из
                # списков выбора, но его отчётность остаётся в базе и в отчётах за
                # прошлые периоды — в этом и смысл флага вместо удаления (SCH-10).
                if mode == MODE_AIRLINE:
                    rows = (
                        session.query(Airline)
                        .filter(Airline.is_active.is_(True))
                        .order_by(Airline.name)
                        .all()
                    )
                    seen: set = set()
                    result: list = [(None, "Все")]
                    for e in rows:
                        eid = e.id
                        if eid in seen:
                            continue
                        seen.add(eid)
                        result.append((eid, e.name.strip()))
                else:
                    rows = (
                        session.query(Airport)
                        .filter(Airport.is_active.is_(True))
                        .order_by(Airport.name)
                        .all()
                    )
                    seen = set()
                    result = [(None, "Все")]
                    for e in rows:
                        eid = e.id
                        if eid in seen:
                            continue
                        seen.add(eid)
                        result.append((eid, e.name.strip()))
                self._cache.put_entities(mode, result)
                return result
        except Exception:
            log.exception("Не удалось загрузить список предприятий")
            return [(None, "Все")]

    def load_indicators(self) -> list:
        """Загружает список показателей"""
        cached = self._cache.indicators()
        if cached is not None:
            return cached

        try:
            with get_session() as session:
                indicators = session.query(Indicator).order_by(Indicator.name).all()
                seen = set()
                result = [(None, "Все показатели")]
                for i in indicators:
                    iid = i.id
                    if iid in seen:
                        continue
                    seen.add(iid)
                    result.append((iid, i.name.strip()))
                self._cache.put_indicators(result)
                return result
        except Exception:
            log.exception("Не удалось загрузить список показателей")
            return [(None, "Все показатели")]

    def get_period_range(self) -> Tuple[int, int, int, int]:
        """Получает минимальный и максимальный год и месяц из данных"""
        try:
            with get_session() as session:
                min_year_al = session.query(func.min(AirlineIndicators.year)).scalar()
                max_year_al = session.query(func.max(AirlineIndicators.year)).scalar()
                min_year_ap = session.query(func.min(AirportIndicators.year)).scalar()
                max_year_ap = session.query(func.max(AirportIndicators.year)).scalar()

                years = [y for y in (min_year_al, max_year_al, min_year_ap, max_year_ap) if y is not None]
                if not years:
                    return 2024, 2025, 1, 12

                min_year = min(years)
                max_year = max(years)
                return min_year, max_year, 1, 12
        except Exception:
            return 2024, 2025, 1, 12

    def get_current_filters(self, filter_widget) -> Dict:
        """Собирает фильтры: списки для SQL IN; при одном элементе — также *_id для свода по одной сущности."""
        filters: Dict[str, Any] = {}

        if filter_widget.current_mode == MODE_AIRLINE:
            air_ids = filter_widget.get_airline_filter_ids()
            if air_ids is not None:
                filters["airline_ids"] = [int(x) for x in air_ids]
                if len(air_ids) == 1:
                    filters["airline_id"] = int(air_ids[0])
            lay = filter_widget.get_pivot_table_layout()
            if lay:
                filters["pivot_table_layout"] = lay
        else:
            ap_ids = filter_widget.get_airport_filter_ids()
            if ap_ids is not None:
                filters["airport_ids"] = [int(x) for x in ap_ids]
                if len(ap_ids) == 1:
                    filters["airport_id"] = int(ap_ids[0])

        ind_ids = filter_widget.get_indicator_filter_ids()
        if ind_ids is not None:
            filters["indicator_ids"] = [int(x) for x in ind_ids]
            if len(ind_ids) == 1:
                filters["indicator_id"] = int(ind_ids[0])

        from_month_key = filter_widget.get_from_month()
        from_year = filter_widget.get_from_year()
        to_month_key = filter_widget.get_to_month()
        to_year = filter_widget.get_to_year()

        if from_month_key and from_year and to_month_key and to_year:
            from_month_idx = MONTHS_LIST.index(from_month_key) + 1
            to_month_idx = MONTHS_LIST.index(to_month_key) + 1
            filters["period_from"] = (from_year, from_month_idx)
            filters["period_to"] = (to_year, to_month_idx)

        if filter_widget.current_mode == MODE_AIRLINE:
            rts = filter_widget.get_route_filter_types()
            if rts is not None:
                filters["route_types"] = list(rts)
                if len(rts) == 1:
                    filters["route_type"] = rts[0]

        return filters

    def get_airport_tab_filters(self, airport_filter_widget) -> Dict:
        """Фильтры вкладки «Аэропорты» (форма 15-ГА): один аэропорт из комбобокса."""
        filters: Dict[str, Any] = {}
        aid = airport_filter_widget.get_airport_id()
        if aid is not None:
            filters["airport_id"] = int(aid)
            filters["airport_ids"] = [int(aid)]

        ind_ids = airport_filter_widget.get_indicator_filter_ids()
        if ind_ids is not None:
            filters["indicator_ids"] = [int(x) for x in ind_ids]
            if len(ind_ids) == 1:
                filters["indicator_id"] = int(ind_ids[0])

        from_month_key = airport_filter_widget.get_from_month()
        from_year = airport_filter_widget.get_from_year()
        to_month_key = airport_filter_widget.get_to_month()
        to_year = airport_filter_widget.get_to_year()

        if from_month_key and from_year and to_month_key and to_year:
            from_month_idx = MONTHS_LIST.index(from_month_key) + 1
            to_month_idx = MONTHS_LIST.index(to_month_key) + 1
            filters["period_from"] = (from_year, from_month_idx)
            filters["period_to"] = (to_year, to_month_idx)

        return filters

    def clear_cache(self):
        """Сбрасывает общий кеш справочников — для всех контроллеров сразу."""
        self._cache.clear()
