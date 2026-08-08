# controllers/filter_controller.py
import logging
from typing import Dict, Optional, Tuple, Any
from sqlalchemy import func, select
from controllers.reference_cache import ReferenceDataCache, reference_cache
from db.database import get_session
from db.models.entities import Airline, Airport, Indicator, AirlineIndicators, AirportIndicators
from utils.constants import MONTHS_LIST, MODE_AIRLINE

log = logging.getLogger(__name__)



def period_from_widget(widget):
    """Границы периода из комбобоксов виджета: ((год, месяц), (год, месяц)) или None.

    Одно чтение на оба места, где период собирался: код был дословно повторён во
    вкладке авиакомпаний и во вкладке аэропортов, и правило порядка границ
    (BUG-16) пришлось бы вводить дважды.
    """
    from_month_key = widget.get_from_month()
    from_year = widget.get_from_year()
    to_month_key = widget.get_to_month()
    to_year = widget.get_to_year()

    if not (from_month_key and from_year and to_month_key and to_year):
        return None

    return (
        (from_year, MONTHS_LIST.index(from_month_key) + 1),
        (to_year, MONTHS_LIST.index(to_month_key) + 1),
    )


def period_is_inverted(bounds) -> bool:
    """Начало периода позже его конца.

    Отбор идёт по условию «начало ≤ ключ ≤ конец», и при перевёрнутых границах
    оно не выполняется ни для одной записи: пользователь получал пустой отчёт
    без единого объяснения (BUG-16).
    """
    return bounds is not None and bounds[0] > bounds[1]


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
                model = Airline if mode == MODE_AIRLINE else Airport
                rows = (
                    session.query(model)
                    .filter(model.is_active.is_(True))
                    .order_by(model.name)
                    .all()
                )
                # Ни отсева дублей по id, ни элемента «Все» здесь больше нет:
                # id — первичный ключ и повторяться не может, а «Все» все
                # вызывающие стороны немедленно отфильтровывали (PERF-9).
                result = [(e.id, e.name.strip()) for e in rows]
                self._cache.put_entities(mode, result)
                return result
        except Exception:
            log.exception("Не удалось загрузить список предприятий")
            return []

    def load_indicators(self) -> list:
        """Загружает список показателей"""
        cached = self._cache.indicators()
        if cached is not None:
            return cached

        try:
            with get_session() as session:
                indicators = session.query(Indicator).order_by(Indicator.name).all()
                result = [(i.id, i.name.strip()) for i in indicators]
                self._cache.put_indicators(result)
                return result
        except Exception:
            log.exception("Не удалось загрузить список показателей")
            return []

    def get_period_range(self) -> Tuple[int, int, int, int]:
        """Получает минимальный и максимальный год и месяц из данных"""
        try:
            with get_session() as session:
                # Один запрос вместо четырёх: минимум и максимум берутся одним
                # агрегатом на таблицу, а обе таблицы соединены UNION ALL. Прежде
                # это были четыре отдельных полных сканирования, и выполнялись
                # они при сборке каждого виджета фильтров и при каждом сбросе
                # (PERF-9).
                extremes = select(
                    func.min(AirlineIndicators.year), func.max(AirlineIndicators.year)
                ).union_all(
                    select(func.min(AirportIndicators.year), func.max(AirportIndicators.year))
                )
                years = [
                    year for row in session.execute(extremes)
                    for year in row if year is not None
                ]
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

        bounds = period_from_widget(filter_widget)
        if bounds is not None:
            filters["period_from"], filters["period_to"] = bounds

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

        bounds = period_from_widget(airport_filter_widget)
        if bounds is not None:
            filters["period_from"], filters["period_to"] = bounds

        return filters

    def clear_cache(self):
        """Сбрасывает общий кеш справочников — для всех контроллеров сразу."""
        self._cache.clear()
