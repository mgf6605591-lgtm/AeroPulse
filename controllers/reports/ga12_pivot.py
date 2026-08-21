"""Своды формы 12-ГА: все авиакомпании, несколько по маршрутам, одна, одна свёрнутая.

Четыре построителя и общий для них обход бланка. Отличаются они только тем, что
кладут в ячейку и какие колонки заводят; порядок строк — разделы, «в том числе»,
показатели — один на всех и живёт в `_emit_form_rows`.
"""
import re
from collections import defaultdict
from decimal import Decimal
from typing import Any

from controllers.airline_ind_service import AirlineIndicatorService
from controllers.report_filters import NO_FILTERS, ReportFilters, with_airline
from controllers.reports.common import (
    EMPTY_PERIOD,
    aggregate_period,
    aggregate_total,
    dec_to_float,
    period_col_key,
    period_count,
    period_label,
    sorted_periods,
)
from db.database import get_session
from db.models.entities import Airline, Indicator
from db.models.enums import RouteType, ShippingRegularity
from utils.constants import (
    GA12_CODES_BY_SECTION,
    GA12_CODE_ORDER_FLAT,
    GA12_DETAIL_TON_CODES,
    GA12_GRAND_TOTAL_HEADER,
    GA12_SECTION_TITLE,
    GA12_SUBHEADING_VTOM,
    GA12_TON_PARENT_CODES,
    GA12_TOTAL_HEADER,
    REGULARITY_ORDER,
    ROUTE_TYPES_ORDER,
    ROUTE_TYPE_NAMES,
)
from utils.ga12_layout import ga12_total_route_types


# Ключ крайней правой колонки общего свода. Под группу месяца он не подходит:
# у тех ключи начинаются с `m_<период>_`.
GA12_GRAND_TOTAL_KEY = "grand_total"


def _route_type_keys_for_total_sum(selected_route_type_names: list[str]) -> set[str]:
    """Виды сообщения, по которым складывается итог.

    Прежняя версия исходила из обратной вложенности — будто «Местные» включают
    внутренние и субсидируемые, — и при выборе одного вида работала лишь потому,
    что лишние ключи отсекались SQL-фильтром и давали нули. Без фильтра по
    маршрутам в сумму шли все четыре вида, то есть местные и субсидируемые
    считались дважды: в бланке они подписаны «из них» и входят в графу
    «Внутренние — всего» (см. GA12_ROUTE_PARENT).
    """
    return ga12_total_route_types(selected_route_type_names)


def _collapse_route_types(raw: dict[tuple, Decimal], target: dict[str, Any]) -> None:
    """Сворачивает `(ключ, период, предприятие, вид сообщения) → значение` в итог.

    Итог берётся не по всем видам сообщения, а только по невложенным: см.
    `_route_type_keys_for_total_sum`.
    """
    buckets: dict[tuple, dict[str, Decimal]] = defaultdict(dict)
    for (key, period, entity, route_type), value in raw.items():
        buckets[(key, period, entity)][route_type] = value

    for (key, period, entity), by_route in buckets.items():
        total_keys = ga12_total_route_types(by_route)
        target[key][period][entity] = sum(
            (by_route[k] for k in total_keys), Decimal("0")
        )


def _okei_sort_key(code: str) -> tuple:
    """Запасной порядок: числовая часть кода ОКЕИ, затем суффикс (н, п, …)."""
    if not code:
        return (999999, "\uffff", "")
    s = str(code).strip().lower().replace(" ", "")
    m = re.match(r"^(\d+)(.*)$", s)
    if not m:
        return (999999, s, "")
    return (int(m.group(1)), m.group(2), "")


def _ga12_form_sort_key(code: str) -> tuple:
    """Порядок строк как в типовом Excel 12-ГА (GA12_CODE_ORDER_FLAT)."""
    c = (code or "").strip()
    try:
        return (0, GA12_CODE_ORDER_FLAT.index(c))
    except ValueError:
        return (1,) + _okei_sort_key(c)


def _pivot_text_row(keys: list[str], text: str) -> dict[str, Any]:
    """Строка свода без чисел: заголовок раздела или подзаголовок «в том числе».

    Обе строились двумя функциями, отличавшимися только оформлением подписи
    (ARCH-8). Оформление — дело вызывающего, а пустая строка у них одна.
    """
    row: dict[str, Any] = {"indicator": text, "measure": ""}
    if "code" in keys:
        row["code"] = ""
    start_fill = 3 if "code" in keys else 2
    for k in keys[start_fill:]:
        row[k] = None
    return row


def _pivot_section_header_row(keys: list[str], title: str) -> dict[str, Any]:
    return _pivot_text_row(keys, f"— {title} —")


def _pivot_subheading_row(keys: list[str], text: str) -> dict[str, Any]:
    return _pivot_text_row(keys, text)


def _count_ga12_data_rows(pivot_rows: list[dict[str, Any]]) -> int:
    """Строки с данными: без заголовков разделов и подзаголовка «в том числе»."""
    return sum(
        1 for r in pivot_rows
        if r.get("indicator")
        and not str(r["indicator"]).startswith("—")
        and r["indicator"] != GA12_SUBHEADING_VTOM
    )


def _load_indicator_graph(session) -> tuple:
    rows = session.query(Indicator).all()
    id_to_code = {r.id: (r.code or "").strip() for r in rows}
    id_to_parent_id = {r.id: r.parent_id for r in rows}
    return id_to_code, id_to_parent_id


def _code_to_indicator_map(session) -> dict[str, Indicator]:
    """Код ОКЕИ → запись indicators (имена строк таблицы только из БД)."""
    return {(r.code or "").strip(): r for r in session.query(Indicator).all() if r.code}


def _emit_vtom_before_row(
    code: str,
    name_to_id: dict[str, int],
    id_to_code: dict[int, str],
    id_to_parent_id: dict[int, int | None],
    ind_name: str,
    vtom_done: bool,
) -> bool:
    if vtom_done:
        return False
    if code in GA12_DETAIL_TON_CODES:
        return True
    iid = name_to_id.get(ind_name)
    if not iid:
        return False
    pid = id_to_parent_id.get(iid)
    if not pid:
        return False
    return id_to_code.get(pid) in GA12_TON_PARENT_CODES


def _fill_airline_columns(row, periods, airlines, by_period) -> None:
    """Колонки свода по всем АК: «Свод» за период, предприятия и общий «Итого».

    «Свод» — итог месяца по выбранным авиакомпаниям, `grand_total` — тот же итог
    за все показанные месяцы разом. Складываются они из одних и тех же значений,
    поэтому и считаются в одном обходе: иначе крайняя правая колонка могла бы
    разойтись с суммой колонок «Свод» у себя же в строке.
    """
    grand_total = Decimal("0")
    for period in periods:
        period_data = by_period.get(period, {})
        pk = period_col_key(period)
        total = Decimal("0")
        for airline in airlines:
            total += period_data.get(airline, Decimal("0"))
        grand_total += total
        row[f"m_{pk}_total"] = dec_to_float(total)
        for index, airline in enumerate(airlines):
            row[f"m_{pk}_a_{index}"] = dec_to_float(period_data.get(airline, Decimal("0")))
    row[GA12_GRAND_TOTAL_KEY] = dec_to_float(grand_total)


def _emit_form_rows(keys, code_to_indicator, fill_cells, vtom_context=None) -> list[dict[str, Any]]:
    """Строки свода в порядке бланка: разделы, «в том числе», строки показателей.

    Один обход на все своды. Прежде он был скопирован в каждый построитель, и
    любая правка бланка требовала синхронного изменения в четырёх местах — так
    DATA-1 и оказалась воспроизведена во всех четырёх копиях сразу (ARCH-4).

    Отличаются своды только содержимым ячеек, поэтому его заполняет переданный
    `fill_cells(row, section_key, code, ind_name)`; всё остальное — общее.

    `vtom_context` — тройка (name_to_id, id_to_code, id_to_parent_id) для сводов,
    которые ставят подзаголовок «в том числе» ещё и по связи parent_id, а не
    только по списку кодов детализации.
    """
    rows: list[dict[str, Any]] = []

    for section_key in REGULARITY_ORDER:
        codes_in_db = [
            code for code in GA12_CODES_BY_SECTION.get(section_key, [])
            if code in code_to_indicator
        ]
        if not codes_in_db:
            continue

        rows.append(_pivot_section_header_row(keys, GA12_SECTION_TITLE.get(section_key, section_key)))
        vtom_done = False

        for code in codes_in_db:
            indicator = code_to_indicator[code]
            ind_name = indicator.name.strip()

            if code in GA12_DETAIL_TON_CODES and not vtom_done:
                rows.append(_pivot_subheading_row(keys, GA12_SUBHEADING_VTOM))
                vtom_done = True

            if vtom_context is not None:
                name_to_id, id_to_code, id_to_parent_id = vtom_context
                if _emit_vtom_before_row(
                    code, name_to_id, id_to_code, id_to_parent_id, ind_name, vtom_done
                ):
                    rows.append(_pivot_subheading_row(keys, GA12_SUBHEADING_VTOM))
                    vtom_done = True

            row: dict[str, Any] = {
                "indicator": ind_name,
                "measure": (indicator.measure or "").strip(),
                "code": code,
            }
            fill_cells(row, section_key, code, ind_name)
            rows.append(row)

    return rows


def _norm_route_type(rt) -> str:
    """Имя члена RouteType (trunk, local, …) для сопоставления с ROUTE_TYPES_ORDER."""
    if isinstance(rt, RouteType):
        return rt.name
    if isinstance(rt, str):
        s = rt.strip()
        for e in RouteType:
            if e.name == s or e.value == s:
                return e.name
    return str(rt).strip()


def _norm_regularity(reg) -> str:
    """Имя члена ShippingRegularity (regular, irregular, …) — ключ раздела свода.

    Возвращалась русская подпись (`.value`), и ею же ключевались словари
    агрегации, порядок разделов и списки кодов. Правка подписи — например
    «Не регулярные» на «Нерегулярные» — рассогласовала бы их молча: записи
    перестали бы попадать в раздел, и он стал бы пустым без единой ошибки
    (ARCH-6). Соседний `_norm_route_type` всегда возвращал имя члена; теперь
    соглашение одно на оба.
    """
    if isinstance(reg, ShippingRegularity):
        return reg.name
    if isinstance(reg, str):
        s = reg.strip()
        for e in ShippingRegularity:
            if e.name == s or e.value == s:
                return e.name
    return str(reg).strip()


def all_airlines(filters: ReportFilters) -> dict[str, Any]:
    """Сводная таблица для всех авиакомпаний (полный бланк 12-ГА; без данных — нули)."""
    rows = AirlineIndicatorService.aggregate(filters)

    ind_by_code: dict[str, Any] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: Decimal('0')))
    )
    ind_by_name_nocode: dict[str, Any] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: Decimal('0')))
    )
    measure_nocode: dict[str, str] = {}
    airlines = set()
    periods_seen: set[tuple] = set()

    # Значения копятся раздельно по видам сообщения и сворачиваются ниже:
    # местные и субсидируемые входят во внутренние, поэтому сложение всех
    # видов подряд учитывало бы их дважды (BUG-2).
    raw_by_code: dict[tuple, Decimal] = defaultdict(lambda: Decimal('0'))
    raw_by_name: dict[tuple, Decimal] = defaultdict(lambda: Decimal('0'))

    n_records = 0
    for row in rows:
        airline_name = (row.airline_name or "").strip()
        period = aggregate_period(row)
        airlines.add(airline_name)
        periods_seen.add(period)
        n_records += row.records
        code = (row.indicator_code or "").strip()
        rt_key = _norm_route_type(row.route_type)
        total = aggregate_total(row)
        if code:
            raw_by_code[(code, period, airline_name, rt_key)] += total
        else:
            ind_name = (row.indicator_name or "").strip()
            raw_by_name[(ind_name, period, airline_name, rt_key)] += total
            measure_nocode[ind_name] = (row.measure or "").strip()

    _collapse_route_types(raw_by_code, ind_by_code)
    _collapse_route_types(raw_by_name, ind_by_name_nocode)

    with get_session() as session:
        code_to_row = {
            (r.code or "").strip(): r
            for r in session.query(Indicator).all()
            if r.code
        }

    airline_names = sorted(airlines)
    periods = sorted_periods(periods_seen) or [EMPTY_PERIOD]

    headers = ["Показатель", "Ед. изм.", "Код ОКЕИ"]
    keys = ["indicator", "measure", "code"]
    groups = []

    col = len(headers)
    for period in periods:
        first = col
        pk = period_col_key(period)
        headers.append("Свод")
        keys.append(f"m_{pk}_total")
        col += 1
        for i, airline in enumerate(airline_names):
            headers.append(airline)
            keys.append(f"m_{pk}_a_{i}")
            col += 1
        last = col - 1
        groups.append((first, last, period_label(period)))

    # Общий итог — крайняя правая колонка и вне групп месяцев: он относится ко
    # всей строке сразу, а не к одному из периодов. Заголовок без группы над ним
    # рисуется на всю высоту шапки (см. forms/widgets/multilevel_header.py).
    headers.append(GA12_GRAND_TOTAL_HEADER)
    keys.append(GA12_GRAND_TOTAL_KEY)

    known_codes = set(GA12_CODE_ORDER_FLAT)

    def fill_cells_for_code(row, section_key, code, ind_name):
        _fill_airline_columns(row, periods, airline_names, ind_by_code.get(code, {}))

    def data_row_for_code(code: str) -> dict[str, Any] | None:
        """Отдельная строка по коду — для раздела «прочие показатели»."""
        ind = code_to_row.get(code)
        if not ind:
            return None
        row: dict[str, Any] = {
            "indicator": ind.name.strip(),
            "measure": (ind.measure or "").strip(),
            "code": code,
        }
        _fill_airline_columns(row, periods, airline_names, ind_by_code.get(code, {}))
        return row

    def data_row_for_name_nocode(ind_name: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "indicator": ind_name,
            "measure": measure_nocode.get(ind_name, ""),
            "code": "",
        }
        _fill_airline_columns(row, periods, airline_names, ind_by_name_nocode.get(ind_name, {}))
        return row

    # Свод по всем АК не ставит «в том числе» по связи parent_id: строка
    # показателя здесь одна на код, а не на пару (раздел, название).
    pivot_rows = _emit_form_rows(keys, code_to_row, fill_cells_for_code)

    orphan_codes = sorted(
        [c for c in ind_by_code.keys() if c not in known_codes and c in code_to_row],
        key=lambda c: _ga12_form_sort_key(c),
    )
    orphan_names = sorted(ind_by_name_nocode.keys())
    if orphan_codes or orphan_names:
        pivot_rows.append(_pivot_section_header_row(keys, "ПРОЧИЕ ПОКАЗАТЕЛИ"))
        for code in orphan_codes:
            row = data_row_for_code(code)
            if row:
                pivot_rows.append(row)
        for ind_name in orphan_names:
            pivot_rows.append(data_row_for_name_nocode(ind_name))

    n_data_rows = _count_ga12_data_rows(pivot_rows)

    return {
        'rows': pivot_rows,
        'headers': headers,
        'keys': keys,
        'groups': groups,
        'stats': {
            'indicators': n_data_rows,
            'airlines': len(airline_names),
            'months': period_count(periods),
            'records': n_records
        }
    }


def _compute_airline_routes_pivot(
    rows: list[Any], filters: ReportFilters | None
) -> dict[str, Any]:
    """Общая сетка 12-ГА: месяцы × виды маршрута + ИТОГО (выборка уже по одной АК)."""
    data: dict[tuple, dict[tuple, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    )
    periods_seen: set[tuple] = set()
    name_to_id: dict[str, int] = {}
    n_records = 0

    for row in rows:
        ind_name = (row.indicator_name or "").strip()
        reg_key = _norm_regularity(row.regularity)
        rt_key = _norm_route_type(row.route_type)
        period = aggregate_period(row)

        periods_seen.add(period)
        n_records += row.records
        name_to_id.setdefault(ind_name, row.indicator_id)
        data[(reg_key, ind_name)][period][rt_key] += aggregate_total(row)
    code_to_indicator: dict[str, Indicator] = {}
    with get_session() as session:
        id_to_code, id_to_parent_id = _load_indicator_graph(session)
        code_to_indicator = _code_to_indicator_map(session)
        for ind in code_to_indicator.values():
            n = ind.name.strip()
            if n not in name_to_id:
                name_to_id[n] = ind.id

    periods = sorted_periods(periods_seen) or [EMPTY_PERIOD]

    f = filters if filters is not None else NO_FILTERS
    if f.route_types:
        route_types_to_show = [getattr(rt, "name", rt) for rt in f.route_types]
    else:
        route_types_to_show = ROUTE_TYPES_ORDER

    headers = ["Показатель", "Ед. изм.", "Код ОКЕИ"]
    keys = ["indicator", "measure", "code"]
    groups = []

    col = len(headers)
    for period in periods:
        first = col
        pk = period_col_key(period)
        for rt in route_types_to_show:
            headers.append(ROUTE_TYPE_NAMES[rt])
            keys.append(f"m_{pk}_rt_{rt}")
            col += 1
        headers.append(GA12_TOTAL_HEADER)
        keys.append(f"m_{pk}_total")
        col += 1
        last = col - 1
        groups.append((first, last, period_label(period)))

    total_keys = _route_type_keys_for_total_sum(route_types_to_show)

    def fill_cells(row, section_key, code, ind_name):
        inner = data.get((section_key, ind_name))
        for period in periods:
            period_data = inner.get(period, {}) if inner is not None else {}
            pk = period_col_key(period)
            for rt in route_types_to_show:
                row[f"m_{pk}_rt_{rt}"] = dec_to_float(period_data.get(rt, Decimal("0")))
            total = sum(period_data.get(k, Decimal("0")) for k in total_keys)
            row[f"m_{pk}_total"] = dec_to_float(total)

    pivot_rows = _emit_form_rows(
        keys, code_to_indicator, fill_cells,
        vtom_context=(name_to_id, id_to_code, id_to_parent_id),
    )

    n_indicators = _count_ga12_data_rows(pivot_rows)

    return {
        "rows": pivot_rows,
        "headers": headers,
        "keys": keys,
        "groups": groups,
        "periods": periods,
        "n_indicators": n_indicators,
        "n_records": n_records,
    }


def multi_airline_by_routes(filters: ReportFilters) -> dict[str, Any]:
    """Несколько АК: по маршрутам; внутри каждого месяца — все выбранные а/к (без данных — нули)."""
    aggregate = AirlineIndicatorService.aggregate(filters)

    f = filters if filters is not None else NO_FILTERS
    if f.airline_ids:
        ids = list(f.airline_ids)
        with get_session() as session:
            selected = session.query(Airline).filter(Airline.id.in_(ids)).all()
        id_to_name = {a.id: a.name.strip() for a in selected}
        airline_rows = [(i, id_to_name[i]) for i in ids if i in id_to_name]
    else:
        with get_session() as session:
            airline_rows = [
                (a.id, a.name.strip())
                for a in session.query(Airline).order_by(Airline.name).all()
            ]

    if not airline_rows:
        seen: dict[int, str] = {}
        for row in aggregate:
            seen[row.airline_id] = (row.airline_name or "").strip()
        airline_rows = sorted(seen.items(), key=lambda x: x[1])

    # (регулярность, имя показателя) -> период -> airline_id -> route_type -> сумма
    data: dict[tuple, dict[tuple, dict[int, dict[str, Decimal]]]] = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(lambda: Decimal("0"))
            )
        )
    )
    periods_seen: set[tuple] = set()
    name_to_id: dict[str, int] = {}
    n_records = 0

    for row in aggregate:
        ind_name = (row.indicator_name or "").strip()
        reg_key = _norm_regularity(row.regularity)
        rt_key = _norm_route_type(row.route_type)
        period = aggregate_period(row)
        periods_seen.add(period)
        n_records += row.records
        name_to_id.setdefault(ind_name, row.indicator_id)
        data[(reg_key, ind_name)][period][row.airline_id][rt_key] += aggregate_total(row)
    code_to_indicator: dict[str, Indicator] = {}
    with get_session() as session:
        id_to_code, id_to_parent_id = _load_indicator_graph(session)
        code_to_indicator = _code_to_indicator_map(session)
        for ind in code_to_indicator.values():
            n = ind.name.strip()
            if n not in name_to_id:
                name_to_id[n] = ind.id

    periods = sorted_periods(periods_seen) or [EMPTY_PERIOD]

    if f.route_types:
        route_types_to_show = [getattr(rt, "name", rt) for rt in f.route_types]
    else:
        route_types_to_show = ROUTE_TYPES_ORDER

    headers = ["Показатель", "Ед. изм.", "Код ОКЕИ"]
    keys = ["indicator", "measure", "code"]
    groups = []
    col = len(headers)

    for period in periods:
        first = col
        pk = period_col_key(period)
        for aid, aname in airline_rows:
            for rt in route_types_to_show:
                headers.append(f"{aname} — {ROUTE_TYPE_NAMES[rt]}")
                keys.append(f"m_{pk}_aid_{aid}_rt_{rt}")
                col += 1
            headers.append(f"{aname} — {GA12_TOTAL_HEADER}")
            keys.append(f"m_{pk}_aid_{aid}_total")
            col += 1
        last = col - 1
        groups.append((first, last, period_label(period)))

    total_keys = _route_type_keys_for_total_sum(route_types_to_show)

    def fill_cells(row, section_key, code, ind_name):
        inner = data.get((section_key, ind_name))
        for period in periods:
            period_bucket = inner[period] if inner is not None else None
            pk = period_col_key(period)
            for aid, _ in airline_rows:
                for rt in route_types_to_show:
                    val = period_bucket[aid][rt] if period_bucket is not None else Decimal("0")
                    row[f"m_{pk}_aid_{aid}_rt_{rt}"] = dec_to_float(val)
                total = Decimal("0")
                if period_bucket is not None:
                    for key in total_keys:
                        total += period_bucket[aid][key]
                row[f"m_{pk}_aid_{aid}_total"] = dec_to_float(total)

    pivot_rows = _emit_form_rows(
        keys, code_to_indicator, fill_cells,
        vtom_context=(name_to_id, id_to_code, id_to_parent_id),
    )

    n_indicators = _count_ga12_data_rows(pivot_rows)

    return {
        "rows": pivot_rows,
        "headers": headers,
        "keys": keys,
        "groups": groups,
        "stats": {
            "indicators": n_indicators,
            "months": period_count(periods),
            "records": n_records,
            "airlines": len(airline_rows),
            "pivot_multi_airline_routes": True,
        },
    }


def per_airline(filters: ReportFilters, airline_id: int) -> dict[str, Any]:
    """Сводная таблица для одной авиакомпании"""
    airline_filters = with_airline(filters, airline_id)

    rows = AirlineIndicatorService.aggregate(airline_filters)

    with get_session() as session:
        al = session.get(Airline, airline_id)
        airline_name = al.name.strip() if al else ""

    base = _compute_airline_routes_pivot(rows, filters)
    return {
        "rows": base["rows"],
        "headers": base["headers"],
        "keys": base["keys"],
        "groups": base["groups"],
        "stats": {
            "airline_name": airline_name,
            "indicators": base["n_indicators"],
            "months": period_count(base["periods"]),
            "records": base["n_records"],
        },
    }


def per_airline_summary(filters: ReportFilters, airline_id: int) -> dict[str, Any]:
    """Свод по одной АК: по месяцам без разбивки по видам маршрута (сумма по учтённым маршрутам за месяц)."""
    airline_filters = with_airline(filters, airline_id)

    aggregate = AirlineIndicatorService.aggregate(airline_filters)

    with get_session() as session:
        al = session.get(Airline, airline_id)
        airline_name = al.name.strip() if al else ""

    data: dict[tuple, dict[tuple, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    )
    periods_seen: set[tuple] = set()
    name_to_id: dict[str, int] = {}
    n_records = 0

    for row in aggregate:
        ind_name = (row.indicator_name or "").strip()
        reg_key = _norm_regularity(row.regularity)
        rt_key = _norm_route_type(row.route_type)
        period = aggregate_period(row)
        periods_seen.add(period)
        n_records += row.records
        name_to_id.setdefault(ind_name, row.indicator_id)
        data[(reg_key, ind_name)][period][rt_key] += aggregate_total(row)

    agg: dict[tuple, dict[Any, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    for (_reg_key, _ind_name), md in data.items():
        for period, rt_dict in md.items():
            # Не `sum(rt_dict.values())`: местные и субсидируемые входят во
            # внутренние, и сумма по всем видам считала бы их дважды.
            total_keys = ga12_total_route_types(rt_dict)
            agg[(_reg_key, _ind_name)][period] += sum(rt_dict[k] for k in total_keys)

    code_to_indicator: dict[str, Indicator] = {}
    with get_session() as session:
        id_to_code, id_to_parent_id = _load_indicator_graph(session)
        code_to_indicator = _code_to_indicator_map(session)
        for ind in code_to_indicator.values():
            n = ind.name.strip()
            if n not in name_to_id:
                name_to_id[n] = ind.id

    periods = sorted_periods(periods_seen) or [EMPTY_PERIOD]

    # «Всего» — сумма показанных колонок. Пока колонки схлопывались, эта сумма
    # была единственным местом, где два года складывались осмысленно; теперь
    # каждый период подписан отдельно, и итог читается однозначно.
    headers = (
        ["Показатель", "Ед. изм.", "Код ОКЕИ"]
        + [period_label(p) for p in periods]
        + ["Всего"]
    )
    keys = (
        ["indicator", "measure", "code"]
        + [f"m_{period_col_key(p)}" for p in periods]
        + ["total"]
    )
    groups: list[tuple] = []

    def fill_cells(row, section_key, code, ind_name):
        inner = agg.get((section_key, ind_name))
        total = Decimal("0")
        for period in periods:
            val = inner.get(period, Decimal("0")) if inner is not None else Decimal("0")
            row[f"m_{period_col_key(period)}"] = dec_to_float(val)
            total += val
        row["total"] = dec_to_float(total)

    pivot_rows = _emit_form_rows(
        keys, code_to_indicator, fill_cells,
        vtom_context=(name_to_id, id_to_code, id_to_parent_id),
    )

    n_indicators = _count_ga12_data_rows(pivot_rows)

    return {
        "rows": pivot_rows,
        "headers": headers,
        "keys": keys,
        "groups": groups,
        "stats": {
            "airline_name": airline_name,
            "indicators": n_indicators,
            "months": period_count(periods),
            "records": n_records,
        },
    }
