"""Бланк 15-ГА на один аэропорт — той же раскладкой, что и в типовом Excel."""
from decimal import Decimal
from typing import Any

from controllers.airport_ind_service import AirportIndicatorService
from controllers.report_filters import ReportFilters, with_airport
from controllers.reports import ga15_metrics
from controllers.reports.common import aggregate_total, dec_to_float, period_label_ru
from controllers.reports.formulas import PivotFormulas
from db.database import get_session
from db.models.entities import Airport
from utils.ga15_airport_layout import (
    GA15_FILTERED_OUT,
    GA15_FLAT_HEADERS,
    GA15_HEADER_GROUPS,
    GA15_KEYS,
    GA15_METRIC_SUMS,
    GA15_METRIC_TAGS,
    GA15_NOT_FILLED,
    GA15_ROW_SUMS,
)


def _metric_key(tag: str) -> str:
    """Ключ колонки бланка по метке её графы."""
    return GA15_KEYS[2 + GA15_METRIC_TAGS.index(tag)]


def _blank_formulas(row_by_code: dict[str, int]) -> PivotFormulas:
    """Итоговые графы и строки бланка — как суммы соседних.

    Ни одну из этих сумм приложение не считает: и графы «Всего», и строки 03,
    07, 08 приходят из отчёта своими показателями. Правило описывает только
    замысел бланка; совпадёт ли сумма с присланным числом, проверяет выгрузка, и
    там, где отчёт не сходится, в книге остаётся число.

    Строка, не попавшая в отбор показателей, в свод не выводится вовсе — тогда
    складывать нечего, и правила для её итога не будет.
    """
    row_sums: dict[int, tuple[int, ...]] = {}
    for code, parts in GA15_ROW_SUMS.items():
        index = row_by_code.get(code)
        operands = tuple(row_by_code[part] for part in parts if part in row_by_code)
        if index is not None and len(operands) == len(parts):
            row_sums[index] = operands

    return PivotFormulas(
        column_sums={
            _metric_key(tag): tuple(_metric_key(part) for part in parts)
            for tag, parts in GA15_METRIC_SUMS.items()
        },
        row_sums=row_sums,
        # Вид перевозок и номер строки — подписи бланка, а не его цифры.
        label_keys=frozenset(GA15_KEYS[:2]),
    )


def _sum_metric(agg: dict[str, Decimal], row_code: str, tag: str) -> tuple:
    total = Decimal("0")
    found = False
    for key in ga15_metrics.metric_code_candidates(row_code, tag):
        if key not in agg:
            continue
        total += agg[key]
        found = True
    return total, found


def build(filters: ReportFilters, airport_id: int) -> dict[str, Any]:
    """Свод 15-ГА для одного аэропорта (структура как в типовом Excel)."""
    airport_filters = with_airport(filters, airport_id)

    rows = AirportIndicatorService.aggregate(airport_filters)

    agg: dict[str, Decimal] = {}
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
    pivot_rows: list[dict[str, Any]] = []
    visible = ga15_metrics.specs_in_filter(selected)
    row_by_code: dict[str, int] = {}

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
                row_by_code[rc] = len(pivot_rows)
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
        note: dict[str, Any] = {k: None for k in GA15_KEYS}
        note[GA15_KEYS[0]] = "Ни один из выбранных показателей не входит в форму 15-ГА."
        pivot_rows.append(note)

    return {
        "rows": pivot_rows,
        "headers": GA15_FLAT_HEADERS,
        "keys": GA15_KEYS,
        "groups": GA15_HEADER_GROUPS,
        "formulas": _blank_formulas(row_by_code),
        "stats": {
            "airport_name": airport_name,
            "layout_ga15": True,
            "records": n_records,
            "indicators": n_data_lines,
        },
    }
