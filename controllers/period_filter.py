# controllers/period_filter.py
"""Отбор по отчётному периоду средствами SQL.

Период задаётся парой (год, месяц) с обеих сторон, поэтому по отдельности ни год,
ни месяц его не выражают: с января 2024 по март 2025 — это не «годы 2024…2025» и
не «месяцы 1…3». Прежде SQL ограничивал выборку годами, а точный отбор делался
перебором уже поднятых записей, причём одинаковым кодом в двух контроллерах
(PERF-1).

Год и месяц сворачиваются в одно число ГГГГММ — в том же виде, в каком период
сравнивался в Python, только теперь это делает база.
"""
from typing import Dict

from sqlalchemy import Integer, cast


def period_key(model):
    """Период записи как одно число: 2025 и март → 202503."""
    # cast нужен, чтобы сравнение шло как с числом: тип колонки месяца знает про
    # перечисление Months и иначе попытался бы истолковать границы диапазона.
    return model.year * 100 + cast(model.month, Integer)


def period_bounds(filters: Dict):
    """Границы периода из фильтров или None, если период не задан целиком."""
    period_from = filters.get("period_from")
    period_to = filters.get("period_to")
    if not period_from or not period_to:
        return None

    year_from, month_from = period_from
    year_to, month_to = period_to
    return year_from * 100 + month_from, year_to * 100 + month_to


def apply_period_filter(query, model, filters: Dict):
    """Добавляет к запросу условие периода, если он задан."""
    bounds = period_bounds(filters)
    if bounds is None:
        return query
    start, end = bounds
    return query.filter(period_key(model).between(start, end))
