"""Сводка 15-ГА по всем аэропортам — как лист «15-ГА» годовой сводки.

Строка на аэропорт, разбивка предприятия под его строкой, «Итого» — сумма
предприятий. Колонки идут периодами сводки: три месяца, квартал, снова три
месяца, квартал, полугодие и так до «12 месяцев».
"""
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set

from controllers.airport_ind_service import AirportIndicatorService
from controllers.report_filters import NO_FILTERS, ReportFilters
from controllers.reports import ga15_metrics
from controllers.reports.common import aggregate_period, aggregate_total, dec_to_float
from db.database import get_session
from db.models.entities import Airport
from utils.constants import MONTHS_LIST
from utils.ga15_airport_layout import GA15_FILTERED_OUT, GA15_METRIC_TAGS
from utils.ga15_summary_layout import (
    GA15_SUMMARY_CHILD_INDENT,
    GA15_SUMMARY_ENTITY_KEY,
    GA15_SUMMARY_ROW_CODE,
    GA15_SUMMARY_TOTAL_TITLE,
    Ga15PeriodBlock,
    summary_columns,
    summary_period_blocks,
)


def _summary_months(
    filters: Optional[ReportFilters], with_data: Set[tuple]
) -> List[tuple]:
    """Месяцы колонок сводки: весь выбранный период, а не только месяцы с цифрами.

    Месяц без отчётности — это ноль, а не отсутствующая колонка. Иначе вместе с
    ним пропал бы и квартал, которому его не хватило, и отчёт за квартал молча
    исчезал бы из сводки из-за одного пустого месяца.

    Период не задан — колонки берутся по данным: показать нечего, кроме того,
    что есть.
    """
    period = (filters or NO_FILTERS).period
    if period is None:
        return sorted(with_data)

    (year_from, month_from), (year_to, month_to) = period
    out: List[tuple] = []
    year, month = year_from, month_from
    while (year, month) <= (year_to, month_to):
        out.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def _tags_by_code() -> Dict[str, str]:
    """Код показателя строки 08 бланка → метка его графы."""
    return {
        code: tag
        for tag in GA15_METRIC_TAGS
        for code in ga15_metrics.metric_code_candidates(GA15_SUMMARY_ROW_CODE, tag)
    }


def _merge_month_buckets(
    data: Dict[int, Dict[tuple, Dict[str, Decimal]]], airport_ids: Sequence[int]
) -> Dict[tuple, Dict[str, Decimal]]:
    """Складывает отчётность нескольких аэропортов в один набор «месяц → графа»."""
    merged: Dict[tuple, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    for airport_id in airport_ids:
        for month, by_tag in data.get(airport_id, {}).items():
            for tag, value in by_tag.items():
                merged[month][tag] += value
    return merged


def _summary_row(
    title: str,
    airport_ids: Sequence[int],
    blocks: Sequence[Ga15PeriodBlock],
    data: Dict[int, Dict[tuple, Dict[str, Decimal]]],
    selected: Optional[Set[str]],
) -> Dict[str, Any]:
    """Строка сводки: аэропорт (или сумма нескольких) по всем колонкам-периодам."""
    buckets = _merge_month_buckets(data, airport_ids)
    row: Dict[str, Any] = {GA15_SUMMARY_ENTITY_KEY: title}

    for block in blocks:
        for tag in GA15_METRIC_TAGS:
            key = f"{block.key}_{tag}"
            # Графа вне отбора — не ноль: нулём отфильтрованную сводку было бы не
            # отличить от сводки, где данных правда нет (FUNC-7).
            if not ga15_metrics.metric_in_filter(selected, GA15_SUMMARY_ROW_CODE, tag):
                row[key] = GA15_FILTERED_OUT
                continue
            total = Decimal("0")
            for month in block.months:
                total += buckets.get(month, {}).get(tag, Decimal("0"))
            row[key] = dec_to_float(total)

    return row


def _rows(
    shown: List[tuple],
    blocks: Sequence[Ga15PeriodBlock],
    data: Dict[int, Dict[tuple, Dict[str, Decimal]]],
    selected: Optional[Set[str]],
) -> tuple:
    """Строки сводки в порядке листа: предприятие, его аэропорты, затем «Итого».

    Аэропорт, чьё предприятие не показано, идёт строкой верхнего уровня и
    входит в итог сам: иначе выбор одного аэропорта из состава предприятия
    давал бы сводку с нулевым итогом.
    """
    shown_ids = {entry[0] for entry in shown}
    children: Dict[int, List[tuple]] = defaultdict(list)
    top: List[tuple] = []
    for airport_id, name, parent_id, _ in shown:
        if parent_id is not None and parent_id in shown_ids:
            children[parent_id].append((airport_id, name))
        else:
            top.append((airport_id, name))

    pivot_rows: List[Dict[str, Any]] = []
    for airport_id, name in top:
        pivot_rows.append(
            _summary_row(name, [airport_id], blocks, data, selected)
        )
        for child_id, child_name in children.get(airport_id, ()):
            pivot_rows.append(
                _summary_row(
                    f"{GA15_SUMMARY_CHILD_INDENT}{child_name}",
                    [child_id],
                    blocks,
                    data,
                    selected,
                )
            )

    pivot_rows.append(
        _summary_row(
            GA15_SUMMARY_TOTAL_TITLE,
            [airport_id for airport_id, _ in top],
            blocks,
            data,
            selected,
        )
    )
    enterprises = [airport_id for airport_id, _ in top if children.get(airport_id)]
    return pivot_rows, len(shown), enterprises


def _empty(headers, keys, groups, message: str) -> Dict[str, Any]:
    """Сводка без единого аэропорта: причина называется прямо, а не пустым листом."""
    return {
        "rows": [{GA15_SUMMARY_ENTITY_KEY: message}],
        "headers": headers,
        "keys": keys,
        "groups": groups,
        "stats": {
            "layout_ga15_summary": True,
            "airports": 0,
            "enterprises": 0,
            "periods": 0,
            "records": 0,
            "indicators": 0,
        },
    }


def build(filters: ReportFilters) -> Dict[str, Any]:
    """Свод по всем аэропортам — как лист «15-ГА» годовой сводки.

    Строка на аэропорт, разбивка предприятия под его строкой, «Итого» —
    сумма предприятий. Складывать все показанные строки подряд нельзя:
    сводный бланк предприятия и есть сумма его аэропортов, и в итоге они
    оказались бы дважды.
    """
    f = filters if filters is not None else NO_FILTERS
    rows = AirportIndicatorService.aggregate(f)

    tag_by_code = _tags_by_code()
    # airport_id → (год, месяц) → метка графы → сумма
    data: Dict[int, Dict[tuple, Dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    )
    months_with_data: Set[tuple] = set()
    n_records = 0

    for row in rows:
        n_records += row.records
        code = (row.indicator_code or "").strip()
        tag = tag_by_code.get(ga15_metrics.CODE_ALIASES.get(code, code))
        if tag is None:
            continue
        year, month_name = aggregate_period(row)
        if month_name not in MONTHS_LIST:
            continue
        month = (year, MONTHS_LIST.index(month_name) + 1)
        months_with_data.add(month)
        data[row.airport_id][month][tag] += aggregate_total(row)

    with get_session() as session:
        catalogue = [
            (ap.id, (ap.name or "").strip(), ap.parent_id, bool(ap.is_active))
            for ap in session.query(Airport).order_by(Airport.name).all()
        ]
        selected = ga15_metrics.selected_codes(session, f)

    blocks = summary_period_blocks(_summary_months(f, months_with_data))
    headers, keys, groups = summary_columns(blocks, GA15_METRIC_TAGS)

    chosen = set(f.airport_ids)
    if chosen:
        shown = [entry for entry in catalogue if entry[0] in chosen]
    else:
        # Выведенное из работы предприятие остаётся в сводке, пока за
        # выбранный период у него есть отчётность: ради этого флаг и заведён
        # вместо удаления (SCH-10).
        shown = [
            entry for entry in catalogue if entry[3] or entry[0] in data
        ]

    if not shown:
        return _empty(
            headers, keys, groups,
            "В справочнике нет аэропортов. Загрузите отчёт или заведите их в «Справочниках».",
        )

    pivot_rows, n_airports, enterprises = _rows(shown, blocks, data, selected)

    return {
        "rows": pivot_rows,
        "headers": headers,
        "keys": keys,
        "groups": groups,
        "stats": {
            "layout_ga15_summary": True,
            "airports": n_airports,
            "enterprises": len(enterprises),
            "periods": len(blocks),
            "records": n_records,
            "indicators": sum(
                1 for tag in GA15_METRIC_TAGS
                if ga15_metrics.metric_in_filter(selected, GA15_SUMMARY_ROW_CODE, tag)
            ),
        },
    }
