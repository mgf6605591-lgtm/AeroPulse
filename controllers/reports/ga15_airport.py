"""Бланк 15-ГА на один аэропорт — той же раскладкой, что и в типовом Excel."""
from decimal import Decimal
from typing import Any, Dict, List

from controllers.airport_ind_service import AirportIndicatorService
from controllers.report_filters import ReportFilters, with_airport
from controllers.reports import ga15_metrics
from controllers.reports.common import aggregate_total, dec_to_float, period_label_ru
from db.database import get_session
from db.models.entities import Airport
from utils.ga15_airport_layout import (
    GA15_FILTERED_OUT,
    GA15_FLAT_HEADERS,
    GA15_HEADER_GROUPS,
    GA15_KEYS,
    GA15_METRIC_TAGS,
    GA15_NOT_FILLED,
)


def _sum_metric(agg: Dict[str, Decimal], row_code: str, tag: str) -> tuple:
    total = Decimal("0")
    found = False
    for key in ga15_metrics.metric_code_candidates(row_code, tag):
        if key not in agg:
            continue
        total += agg[key]
        found = True
    return total, found


def build(filters: ReportFilters, airport_id: int) -> Dict[str, Any]:
    """Свод 15-ГА для одного аэропорта (структура как в типовом Excel)."""
    airport_filters = with_airport(filters, airport_id)

    rows = AirportIndicatorService.aggregate(airport_filters)

    agg: Dict[str, Decimal] = {}
    n_records = 0
    for row in rows:
        code = (row.indicator_code or "").strip()
        n_records += row.records
        if not code:
            continue
        canon = ga15_metrics.CODE_ALIASES.get(code, code)
        agg[canon] = agg.get(canon, Decimal("0")) + aggregate_total(row)

    airport_name = ""
    with get_session() as session:
        ap = session.get(Airport, airport_id)
        airport_name = ap.name.strip() if ap else ""
        selected = ga15_metrics.selected_codes(session, filters)

    period_label = period_label_ru(filters)
    pivot_rows: List[Dict[str, Any]] = []
    visible = ga15_metrics.specs_in_filter(selected)

    for spec in visible:
        row = {k: None for k in GA15_KEYS}
        if spec.kind == "title":
            row[GA15_KEYS[0]] = spec.title.format(airport_name=airport_name)
        elif spec.kind == "spacer":
            row[GA15_KEYS[0]] = ""
        elif spec.kind == "period":
            row[GA15_KEYS[0]] = f"за {period_label}"
        elif spec.kind == "section":
            row[GA15_KEYS[0]] = spec.title
        elif spec.kind == "subheading":
            row[GA15_KEYS[0]] = spec.title
        elif spec.kind in ("data", "subdetail"):
            row[GA15_KEYS[0]] = spec.title
            line_disp = spec.line_display
            row[GA15_KEYS[1]] = line_disp if line_disp is not None else ""
            rc = spec.row_code
            if rc:
                for j, tag in enumerate(GA15_METRIC_TAGS):
                    ci = 2 + j
                    # «Х» — свойство графы бланка, а не признак отсутствия
                    # данных: в заполняемой графе отсутствие данных — ноль.
                    # Прежде вся строка 09 выводилась как «Х», хотя количество
                    # ВС в ней заполняется (BUG-30).
                    if tag in spec.not_filled:
                        row[GA15_KEYS[ci]] = GA15_NOT_FILLED
                        continue
                    # Графа вне отбора — не ноль: нулём отфильтрованный бланк
                    # было бы не отличить от бланка, где данных правда нет
                    # (FUNC-7).
                    if not ga15_metrics.metric_in_filter(selected, rc, tag):
                        row[GA15_KEYS[ci]] = GA15_FILTERED_OUT
                        continue
                    total, found = _sum_metric(agg, rc, tag)
                    row[GA15_KEYS[ci]] = dec_to_float(total) if found else 0.0
        pivot_rows.append(row)

    n_data_lines = sum(
        1 for s in visible if s.kind in ("data", "subdetail") and s.row_code
    )

    # Список показателей в фильтре общий на обе формы, и в нём можно выбрать
    # одни только строки 12-ГА. Пустой бланк под заголовком выглядел бы как
    # отчёт без данных, поэтому причина названа прямо.
    if selected is not None and not n_data_lines:
        note = {k: None for k in GA15_KEYS}
        note[GA15_KEYS[0]] = "Ни один из выбранных показателей не входит в форму 15-ГА."
        pivot_rows.append(note)

    return {
        "rows": pivot_rows,
        "headers": GA15_FLAT_HEADERS,
        "keys": GA15_KEYS,
        "groups": GA15_HEADER_GROUPS,
        "stats": {
            "airport_name": airport_name,
            "layout_ga15": True,
            "records": n_records,
            "indicators": n_data_lines,
        },
    }
