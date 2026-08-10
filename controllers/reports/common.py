"""Общее построителям сводов: периоды колонок и приведение сумм.

Здесь лежит то, чем пользуется больше одной формы. Имена без подчёркивания:
модуль для того и заведён, чтобы его звали снаружи, — а `_имя`, импортированное
из соседнего модуля, обещает обратное.
"""
from decimal import Decimal
from typing import List, Optional, Set

from controllers.report_filters import ReportFilters
from utils.constants import MONTHS_LIST, MONTHS_RU

# Период-заглушка, когда в выборке нет ни одной записи.
EMPTY_PERIOD: tuple = (None, None)


def sorted_periods(periods: Set[tuple]) -> List[tuple]:
    """Периоды в хронологическом порядке: сначала по году, затем по месяцу."""
    def order(period: tuple) -> tuple:
        year, month = period
        month_index = MONTHS_LIST.index(month) if month in MONTHS_LIST else -1
        return (year if year is not None else 0, month_index)

    return sorted(periods, key=order)


def period_col_key(period: tuple) -> str:
    """Часть ключа колонки, обозначающая период. Год входит в ключ обязательно."""
    year, month = period
    return f"{year}_{month}"


def period_label(period: tuple) -> str:
    """Подпись колонки: «Январь 2025». Год указывается всегда, а не подразумевается."""
    year, month = period
    name = MONTHS_RU.get(month, month or "")
    if not name:
        return ""
    return f"{name} {year}" if year is not None else name


def period_count(periods: List[tuple]) -> int:
    """Сколько периодов реально попало в свод.

    Заглушка пустой выборки не считается. Проверять её через истинность нельзя:
    кортеж (None, None) непустой и потому истинен — прежняя проверка `months[0]`
    работала лишь потому, что заглушкой был сам None.
    """
    return 0 if list(periods) == [EMPTY_PERIOD] else len(periods)


def period_label_ru(filters: Optional[ReportFilters]) -> str:
    if not filters:
        return "выбранный период"
    period = filters.period
    if period is None:
        return "выбранный период"
    (yf, mf), (yt, mt) = period
    mk_f = MONTHS_LIST[mf - 1]
    mk_t = MONTHS_LIST[mt - 1]
    if yf == yt and mf == mt:
        return f"{MONTHS_RU.get(mk_f, mk_f)} {yf} г."
    return f"{MONTHS_RU.get(mk_f, mk_f)} {yf} г. — {MONTHS_RU.get(mk_t, mk_t)} {yt} г."


def dec_to_float(v: Decimal) -> float:
    """Безопасное приведение; не использовать `if v` — Decimal('0') даёт False."""
    return float(v)


def aggregate_period(row) -> tuple:
    """Период строки агрегата — та же пара (год, месяц), что и у факта."""
    month = row.month.name if hasattr(row.month, "name") else str(row.month)
    return (row.year, month)


def aggregate_total(row) -> Decimal:
    """Сумма группы обратно в Decimal: дальше свод считает и сворачивает точно."""
    return Decimal(str(row.total or 0))
