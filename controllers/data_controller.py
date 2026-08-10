# controllers/data_controller.py
"""Выбор построителя отчёта и сборка подробной таблицы.

Здесь остался диспетчер: по режиму вкладки и числу выбранных предприятий решить,
какой свод строить, — и позвать построителя из `controllers/reports/`. Сами своды
разъехались по модулям на форму (ARCH-15): прежде все четыре жили в этом файле,
и он занимал 1288 строк.

Подробная таблица осталась здесь: она одна на обе формы и отличается между ними
только набором колонок.
"""
from typing import Any

from controllers.airline_ind_service import AirlineIndicatorService
from controllers.airport_ind_service import AirportIndicatorService
from controllers.report_filters import NO_FILTERS, ReportFilters
from controllers.reports import ga12_pivot, ga15_airport, ga15_summary
from utils.constants import (
    MODE_AIRLINE,
    PIVOT_LAYOUT_BY_ROUTES,
    PIVOT_LAYOUT_SUMMARY,
)


class DataController:
    """Контроллер для управления данными таблиц"""

    def __init__(self):
        self.pivot_model = None
        self.detail_model = None

    def set_models(self, pivot_model, detail_model):
        """Устанавливает модели данных"""
        self.pivot_model = pivot_model
        self.detail_model = detail_model

    def load_pivot_data(self, mode: int, filters: ReportFilters, entity_id: int | None = None) -> dict[str, Any]:
        """Загружает данные для сводной таблицы"""
        if mode == MODE_AIRLINE:
            lay = (filters or NO_FILTERS).pivot_table_layout or PIVOT_LAYOUT_BY_ROUTES
            if entity_id:
                if lay == PIVOT_LAYOUT_SUMMARY:
                    return ga12_pivot.per_airline_summary(filters, entity_id)
                return ga12_pivot.per_airline(filters, entity_id)
            if lay == PIVOT_LAYOUT_BY_ROUTES:
                return ga12_pivot.multi_airline_by_routes(filters)
            return ga12_pivot.all_airlines(filters)
        else:  # MODE_AIRPORT
            # Один аэропорт — бланк 15-ГА, как он приходит; несколько или все —
            # сводка по аэропортам. Так же устроена и вкладка авиакомпаний: вид
            # отчёта выбирает не отдельная настройка, а число выбранных
            # предприятий.
            if entity_id:
                return ga15_airport.build(filters, entity_id)
            return ga15_summary.build(filters)

    def load_detail_data(self, mode: int, filters: ReportFilters) -> dict[str, Any]:
        """Загружает данные для подробной таблицы"""
        if mode == MODE_AIRLINE:
            # Регулярность выводится рядом с типом маршрута: вдвоём они и образуют
            # рейс. Без неё две записи с одним показателем, месяцем и типом
            # маршрута выглядели в таблице одинаково — а удаляют именно отсюда,
            # и отменить удаление нечем (FUNC-11).
            headers = [
                "ID", "Авиакомпания", "Код а/к", "Показатель", "Месяц", "Год",
                "Значение", "Ед. изм.", "Тип маршрута", "Регулярность",
            ]
            # Поля снимка строки (controllers/detail_rows.py), а не пути по связям
            # ORM: за пределами сессии связей уже нет, и путь вроде
            # 'shipping.airline.name' держался на точно подобранных joinedload
            # (BUG-14).
            attrs = [
                'id', 'entity_name', 'entity_code',
                'indicator', 'month', 'year', 'value',
                'measure', 'route_type', 'regularity',
            ]
            records = AirlineIndicatorService.detail_rows(filters)
        else:
            headers = ["ID", "Аэропорт", "Код", "Показатель", "Месяц", "Год", "Значение", "Ед. изм.", "Нас. пункт"]
            attrs = [
                'id', 'entity_name', 'entity_code',
                'indicator', 'month', 'year', 'value',
                'measure', 'locality',
            ]
            records = AirportIndicatorService.detail_rows(filters)

        return {
            'headers': headers,
            'attrs': attrs,
            'records': records
        }
