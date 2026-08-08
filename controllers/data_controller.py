# controllers/data_controller.py
import re
from decimal import Decimal
from collections import defaultdict
from typing import Dict, List, Any, Optional, Set
from db.database import get_session
from db.models.entities import Airline, Airport, Indicator
from db.models.enums import RouteType, ShippingRegularity
from services.airline_ind_service import AirlineIndicatorService
from services.airport_ind_service import AirportIndicatorService
from utils.constants import (
    MONTHS_LIST,
    MONTHS_RU,
    ROUTE_TYPES_ORDER,
    ROUTE_TYPE_NAMES,
    REGULARITY_ORDER,
    GA12_CODE_ORDER_FLAT,
    GA12_CODES_BY_SECTION,
    GA12_SECTION_TITLE,
    GA12_SUBHEADING_VTOM,
    GA12_DETAIL_TON_CODES,
    GA12_TON_PARENT_CODES,
    GA12_TOTAL_HEADER,
    MODE_AIRLINE,
    PIVOT_LAYOUT_BY_ROUTES,
    PIVOT_LAYOUT_SUMMARY,
)
from controllers.report_filters import NO_FILTERS, ReportFilters, with_airline, with_airport
from utils.ga12_layout import ga12_total_route_types
from utils.ga15_airport_layout import (
    GA15_METRIC_TAGS,
    GA15_FLAT_HEADERS,
    GA15_HEADER_GROUPS,
    GA15_KEYS,
    GA15_NOT_FILLED,
    GA15_TABLE_ROWS,
)

# Псевдонимы кода показателя → канонический код вида 15ГА-R05-ПАС_ОТП
GA15_CODE_ALIASES: Dict[str, str] = {}


def _sorted_periods(periods: Set[tuple]) -> List[tuple]:
    """Периоды в хронологическом порядке: сначала по году, затем по месяцу."""
    def order(period: tuple) -> tuple:
        year, month = period
        month_index = MONTHS_LIST.index(month) if month in MONTHS_LIST else -1
        return (year if year is not None else 0, month_index)

    return sorted(periods, key=order)


def _period_col_key(period: tuple) -> str:
    """Часть ключа колонки, обозначающая период. Год входит в ключ обязательно."""
    year, month = period
    return f"{year}_{month}"


def _period_label(period: tuple) -> str:
    """Подпись колонки: «Январь 2025». Год указывается всегда, а не подразумевается."""
    year, month = period
    name = MONTHS_RU.get(month, month or "")
    if not name:
        return ""
    return f"{name} {year}" if year is not None else name


# Период-заглушка, когда в выборке нет ни одной записи.
EMPTY_PERIOD: tuple = (None, None)


def _period_count(periods: List[tuple]) -> int:
    """Сколько периодов реально попало в свод.

    Заглушка пустой выборки не считается. Проверять её через истинность нельзя:
    кортеж (None, None) непустой и потому истинен — прежняя проверка `months[0]`
    работала лишь потому, что заглушкой был сам None.
    """
    return 0 if list(periods) == [EMPTY_PERIOD] else len(periods)


def _period_label_ru(filters: Optional[ReportFilters]) -> str:
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


def _ga15_metric_code_candidates(row_code: str, tag: str) -> List[str]:
    keys = [f"15ГА-{row_code}-{tag}"]
    if re.fullmatch(r"R\d{2}", row_code):
        n = int(row_code[1:])
        keys.append(f"15ГА-{n:02d}-{tag}")
    return keys


def _ga15_sum_metric(agg: Dict[str, Decimal], row_code: str, tag: str) -> tuple:
    total = Decimal("0")
    found = False
    for key in _ga15_metric_code_candidates(row_code, tag):
        if key not in agg:
            continue
        total += agg[key]
        found = True
    return total, found


def _route_type_keys_for_total_sum(selected_route_type_names: List[str]) -> Set[str]:
    """Виды сообщения, по которым складывается итог.

    Прежняя версия исходила из обратной вложенности — будто «Местные» включают
    внутренние и субсидируемые, — и при выборе одного вида работала лишь потому,
    что лишние ключи отсекались SQL-фильтром и давали нули. Без фильтра по
    маршрутам в сумму шли все четыре вида, то есть местные и субсидируемые
    считались дважды: в бланке они подписаны «из них» и входят в графу
    «Внутренние — всего» (см. GA12_ROUTE_PARENT).
    """
    return ga12_total_route_types(selected_route_type_names)


def _collapse_route_types(raw: Dict[tuple, Decimal], target: Dict[str, Any]) -> None:
    """Сворачивает `(ключ, период, предприятие, вид сообщения) → значение` в итог.

    Итог берётся не по всем видам сообщения, а только по невложенным: см.
    `_route_type_keys_for_total_sum`.
    """
    buckets: Dict[tuple, Dict[str, Decimal]] = defaultdict(dict)
    for (key, period, entity, route_type), value in raw.items():
        buckets[(key, period, entity)][route_type] = value

    for (key, period, entity), by_route in buckets.items():
        total_keys = ga12_total_route_types(by_route)
        target[key][period][entity] = sum(
            (by_route[k] for k in total_keys), Decimal("0")
        )


def _dec_to_float(v: Decimal) -> float:
    """Безопасное приведение; не использовать `if v` — Decimal('0') даёт False."""
    return float(v)


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


def _pivot_section_header_row(keys: List[str], title: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {"indicator": f"— {title} —", "measure": ""}
    if "code" in keys:
        row["code"] = ""
    start_fill = 3 if "code" in keys else 2
    for k in keys[start_fill:]:
        row[k] = None
    return row


def _pivot_subheading_row(keys: List[str], text: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {"indicator": text, "measure": ""}
    if "code" in keys:
        row["code"] = ""
    start_fill = 3 if "code" in keys else 2
    for k in keys[start_fill:]:
        row[k] = None
    return row


def _count_ga12_data_rows(pivot_rows: List[Dict[str, Any]]) -> int:
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


def _code_to_indicator_map(session) -> Dict[str, Indicator]:
    """Код ОКЕИ → запись indicators (имена строк таблицы только из БД)."""
    return {(r.code or "").strip(): r for r in session.query(Indicator).all() if r.code}


def _indicator_row_sort_key(
    ind_name: str,
    name_to_id: Dict[str, int],
    id_to_code: Dict[int, str],
    id_to_parent_id: Dict[int, Optional[int]],
    ind_codes: Dict[str, str],
) -> tuple:
    """Дочерние показатели (parent_id) сразу после родителя; порядок а/б/в по GA12_DETAIL_TON_CODES."""
    iid = name_to_id.get(ind_name)
    fb = ind_codes.get(ind_name, "")
    if iid is None:
        return (99,) + _ga12_form_sort_key(fb) + (99, 99)
    pid = id_to_parent_id.get(iid)
    code = id_to_code.get(iid, fb)
    if pid is None:
        return _ga12_form_sort_key(code) + (0, 0)
    pcode = id_to_code.get(pid, "")
    base = _ga12_form_sort_key(pcode)
    if code in GA12_DETAIL_TON_CODES:
        suf = 1 + GA12_DETAIL_TON_CODES.index(code)
    else:
        suf = 50
    return base + (1, suf)


def _emit_vtom_before_row(
    code: str,
    name_to_id: Dict[str, int],
    id_to_code: Dict[int, str],
    id_to_parent_id: Dict[int, Optional[int]],
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


def _aggregate_period(row) -> tuple:
    """Период строки агрегата — та же пара (год, месяц), что и у факта."""
    month = row.month.name if hasattr(row.month, "name") else str(row.month)
    return (row.year, month)


def _aggregate_total(row) -> Decimal:
    """Сумма группы обратно в Decimal: дальше свод считает и сворачивает точно."""
    return Decimal(str(row.total or 0))


def _fill_airline_columns(row, periods, airlines, by_period) -> None:
    """Колонки свода по всем АК: «Свод» за период и по колонке на предприятие."""
    for period in periods:
        period_data = by_period.get(period, {})
        pk = _period_col_key(period)
        total = Decimal("0")
        for airline in airlines:
            total += period_data.get(airline, Decimal("0"))
        row[f"m_{pk}_total"] = _dec_to_float(total)
        for index, airline in enumerate(airlines):
            row[f"m_{pk}_a_{index}"] = _dec_to_float(period_data.get(airline, Decimal("0")))


def _emit_form_rows(keys, code_to_indicator, fill_cells, vtom_context=None) -> List[Dict[str, Any]]:
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
    rows: List[Dict[str, Any]] = []

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

            row: Dict[str, Any] = {
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
    """То же значение, что в REGULARITY_ORDER (русская подпись раздела)."""
    if isinstance(reg, ShippingRegularity):
        return reg.value
    if isinstance(reg, str):
        for e in ShippingRegularity:
            if e.name == reg or e.value == reg:
                return e.value
    return str(reg)


class DataController:
    """Контроллер для управления данными таблиц"""
    
    def __init__(self):
        self.pivot_model = None
        self.detail_model = None
    
    def set_models(self, pivot_model, detail_model):
        """Устанавливает модели данных"""
        self.pivot_model = pivot_model
        self.detail_model = detail_model
    
    def load_pivot_data(self, mode: int, filters: ReportFilters, entity_id: Optional[int] = None) -> Dict[str, Any]:
        """Загружает данные для сводной таблицы"""
        if mode == MODE_AIRLINE:
            if entity_id:
                lay = (filters or NO_FILTERS).pivot_table_layout or PIVOT_LAYOUT_BY_ROUTES
                if lay == PIVOT_LAYOUT_SUMMARY:
                    return self._load_pivot_per_airline_summary(filters, entity_id)
                return self._load_pivot_per_airline(filters, entity_id)
            else:
                lay = (filters or NO_FILTERS).pivot_table_layout or PIVOT_LAYOUT_BY_ROUTES
                if lay == PIVOT_LAYOUT_BY_ROUTES:
                    return self._load_pivot_multi_airline_by_routes(filters)
                return self._load_pivot_all_airlines(filters)
        else:  # MODE_AIRPORT
            if entity_id:
                return self._load_pivot_ga15_airport(filters, entity_id)
            return self._load_pivot_ga15_empty("Выберите аэропорт в списке фильтра.")
    
    def _load_pivot_all_airlines(self, filters: ReportFilters) -> Dict[str, Any]:
        """Сводная таблица для всех авиакомпаний (полный бланк 12-ГА; без данных — нули)."""
        rows = AirlineIndicatorService.aggregate(filters)

        ind_by_code: Dict[str, Any] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: Decimal('0')))
        )
        ind_by_name_nocode: Dict[str, Any] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: Decimal('0')))
        )
        measure_nocode: Dict[str, str] = {}
        airlines = set()
        periods_seen: Set[tuple] = set()

        # Значения копятся раздельно по видам сообщения и сворачиваются ниже:
        # местные и субсидируемые входят во внутренние, поэтому сложение всех
        # видов подряд учитывало бы их дважды (BUG-2).
        raw_by_code: Dict[tuple, Decimal] = defaultdict(lambda: Decimal('0'))
        raw_by_name: Dict[tuple, Decimal] = defaultdict(lambda: Decimal('0'))

        n_records = 0
        for row in rows:
            airline_name = (row.airline_name or "").strip()
            period = _aggregate_period(row)
            airlines.add(airline_name)
            periods_seen.add(period)
            n_records += row.records
            code = (row.indicator_code or "").strip()
            rt_key = _norm_route_type(row.route_type)
            total = _aggregate_total(row)
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

        airlines = sorted(airlines)
        periods = _sorted_periods(periods_seen) or [EMPTY_PERIOD]

        headers = ["Показатель", "Ед. изм.", "Код ОКЕИ"]
        keys = ["indicator", "measure", "code"]
        groups = []

        col = len(headers)
        for period in periods:
            first = col
            pk = _period_col_key(period)
            headers.append("Свод")
            keys.append(f"m_{pk}_total")
            col += 1
            for i, airline in enumerate(airlines):
                headers.append(airline)
                keys.append(f"m_{pk}_a_{i}")
                col += 1
            last = col - 1
            groups.append((first, last, _period_label(period)))

        known_codes = set(GA12_CODE_ORDER_FLAT)

        def fill_cells_for_code(row, section_key, code, ind_name):
            _fill_airline_columns(row, periods, airlines, ind_by_code.get(code, {}))

        def data_row_for_code(code: str) -> Optional[Dict[str, Any]]:
            """Отдельная строка по коду — для раздела «прочие показатели»."""
            ind = code_to_row.get(code)
            if not ind:
                return None
            row: Dict[str, Any] = {
                "indicator": ind.name.strip(),
                "measure": (ind.measure or "").strip(),
                "code": code,
            }
            _fill_airline_columns(row, periods, airlines, ind_by_code.get(code, {}))
            return row

        def data_row_for_name_nocode(ind_name: str) -> Dict[str, Any]:
            row: Dict[str, Any] = {
                "indicator": ind_name,
                "measure": measure_nocode.get(ind_name, ""),
                "code": "",
            }
            _fill_airline_columns(row, periods, airlines, ind_by_name_nocode.get(ind_name, {}))
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
                'airlines': len(airlines),
                'months': _period_count(periods),
                'records': n_records
            }
        }
    
    def _compute_airline_routes_pivot(
        self, rows: List[Any], filters: Optional[ReportFilters]
    ) -> Dict[str, Any]:
        """Общая сетка 12-ГА: месяцы × виды маршрута + ИТОГО (выборка уже по одной АК)."""
        data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: Decimal("0"))))
        periods_seen: Set[tuple] = set()
        name_to_id: Dict[str, int] = {}
        n_records = 0

        for row in rows:
            ind_name = (row.indicator_name or "").strip()
            reg_key = _norm_regularity(row.regularity)
            rt_key = _norm_route_type(row.route_type)
            period = _aggregate_period(row)

            periods_seen.add(period)
            n_records += row.records
            name_to_id.setdefault(ind_name, row.indicator_id)
            data[(reg_key, ind_name)][period][rt_key] += _aggregate_total(row)
        code_to_indicator: Dict[str, Indicator] = {}
        with get_session() as session:
            id_to_code, id_to_parent_id = _load_indicator_graph(session)
            code_to_indicator = _code_to_indicator_map(session)
            for ind in code_to_indicator.values():
                n = ind.name.strip()
                if n not in name_to_id:
                    name_to_id[n] = ind.id

        periods = _sorted_periods(periods_seen) or [EMPTY_PERIOD]

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
            pk = _period_col_key(period)
            for rt in route_types_to_show:
                headers.append(ROUTE_TYPE_NAMES[rt])
                keys.append(f"m_{pk}_rt_{rt}")
                col += 1
            headers.append(GA12_TOTAL_HEADER)
            keys.append(f"m_{pk}_total")
            col += 1
            last = col - 1
            groups.append((first, last, _period_label(period)))

        total_keys = _route_type_keys_for_total_sum(route_types_to_show)

        def fill_cells(row, section_key, code, ind_name):
            inner = data.get((section_key, ind_name))
            for period in periods:
                period_data = inner.get(period, {}) if inner is not None else {}
                pk = _period_col_key(period)
                for rt in route_types_to_show:
                    row[f"m_{pk}_rt_{rt}"] = _dec_to_float(period_data.get(rt, Decimal("0")))
                total = sum(period_data.get(k, Decimal("0")) for k in total_keys)
                row[f"m_{pk}_total"] = _dec_to_float(total)

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

    def _load_pivot_multi_airline_by_routes(self, filters: ReportFilters) -> Dict[str, Any]:
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
            seen: Dict[int, str] = {}
            for row in aggregate:
                seen[row.airline_id] = (row.airline_name or "").strip()
            airline_rows = sorted(seen.items(), key=lambda x: x[1])

        # (регулярность, имя показателя) -> период -> airline_id -> route_type -> сумма
        data = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(lambda: Decimal("0"))
                )
            )
        )
        periods_seen: Set[tuple] = set()
        name_to_id: Dict[str, int] = {}
        n_records = 0

        for row in aggregate:
            ind_name = (row.indicator_name or "").strip()
            reg_key = _norm_regularity(row.regularity)
            rt_key = _norm_route_type(row.route_type)
            period = _aggregate_period(row)
            periods_seen.add(period)
            n_records += row.records
            name_to_id.setdefault(ind_name, row.indicator_id)
            data[(reg_key, ind_name)][period][row.airline_id][rt_key] += _aggregate_total(row)
        code_to_indicator: Dict[str, Indicator] = {}
        with get_session() as session:
            id_to_code, id_to_parent_id = _load_indicator_graph(session)
            code_to_indicator = _code_to_indicator_map(session)
            for ind in code_to_indicator.values():
                n = ind.name.strip()
                if n not in name_to_id:
                    name_to_id[n] = ind.id

        periods = _sorted_periods(periods_seen) or [EMPTY_PERIOD]

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
            pk = _period_col_key(period)
            for aid, aname in airline_rows:
                for rt in route_types_to_show:
                    headers.append(f"{aname} — {ROUTE_TYPE_NAMES[rt]}")
                    keys.append(f"m_{pk}_aid_{aid}_rt_{rt}")
                    col += 1
                headers.append(f"{aname} — {GA12_TOTAL_HEADER}")
                keys.append(f"m_{pk}_aid_{aid}_total")
                col += 1
            last = col - 1
            groups.append((first, last, _period_label(period)))

        total_keys = _route_type_keys_for_total_sum(route_types_to_show)

        def fill_cells(row, section_key, code, ind_name):
            inner = data.get((section_key, ind_name))
            for period in periods:
                period_bucket = inner[period] if inner is not None else None
                pk = _period_col_key(period)
                for aid, _ in airline_rows:
                    for rt in route_types_to_show:
                        val = period_bucket[aid][rt] if period_bucket is not None else Decimal("0")
                        row[f"m_{pk}_aid_{aid}_rt_{rt}"] = _dec_to_float(val)
                    total = Decimal("0")
                    if period_bucket is not None:
                        for key in total_keys:
                            total += period_bucket[aid][key]
                    row[f"m_{pk}_aid_{aid}_total"] = _dec_to_float(total)

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
                "months": _period_count(periods),
                "records": n_records,
                "airlines": len(airline_rows),
                "pivot_multi_airline_routes": True,
            },
        }

    def _load_pivot_per_airline(self, filters: ReportFilters, airline_id: int) -> Dict[str, Any]:
        """Сводная таблица для одной авиакомпании"""
        airline_filters = with_airline(filters, airline_id)

        rows = AirlineIndicatorService.aggregate(airline_filters)

        with get_session() as session:
            al = session.get(Airline, airline_id)
            airline_name = al.name.strip() if al else ""

        base = self._compute_airline_routes_pivot(rows, filters)
        return {
            "rows": base["rows"],
            "headers": base["headers"],
            "keys": base["keys"],
            "groups": base["groups"],
            "stats": {
                "airline_name": airline_name,
                "indicators": base["n_indicators"],
                "months": _period_count(base["periods"]),
                "records": base["n_records"],
            },
        }

    def _load_pivot_per_airline_summary(self, filters: ReportFilters, airline_id: int) -> Dict[str, Any]:
        """Свод по одной АК: по месяцам без разбивки по видам маршрута (сумма по учтённым маршрутам за месяц)."""
        airline_filters = with_airline(filters, airline_id)

        aggregate = AirlineIndicatorService.aggregate(airline_filters)

        with get_session() as session:
            al = session.get(Airline, airline_id)
            airline_name = al.name.strip() if al else ""

        data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: Decimal("0"))))
        periods_seen: Set[tuple] = set()
        name_to_id: Dict[str, int] = {}
        n_records = 0

        for row in aggregate:
            ind_name = (row.indicator_name or "").strip()
            reg_key = _norm_regularity(row.regularity)
            rt_key = _norm_route_type(row.route_type)
            period = _aggregate_period(row)
            periods_seen.add(period)
            n_records += row.records
            name_to_id.setdefault(ind_name, row.indicator_id)
            data[(reg_key, ind_name)][period][rt_key] += _aggregate_total(row)

        agg: Dict[tuple, Dict[Any, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
        for (_reg_key, _ind_name), md in data.items():
            for period, rt_dict in md.items():
                # Не `sum(rt_dict.values())`: местные и субсидируемые входят во
                # внутренние, и сумма по всем видам считала бы их дважды.
                keys = ga12_total_route_types(rt_dict)
                agg[(_reg_key, _ind_name)][period] += sum(rt_dict[k] for k in keys)

        code_to_indicator: Dict[str, Indicator] = {}
        with get_session() as session:
            id_to_code, id_to_parent_id = _load_indicator_graph(session)
            code_to_indicator = _code_to_indicator_map(session)
            for ind in code_to_indicator.values():
                n = ind.name.strip()
                if n not in name_to_id:
                    name_to_id[n] = ind.id

        periods = _sorted_periods(periods_seen) or [EMPTY_PERIOD]

        # «Всего» — сумма показанных колонок. Пока колонки схлопывались, эта сумма
        # была единственным местом, где два года складывались осмысленно; теперь
        # каждый период подписан отдельно, и итог читается однозначно.
        headers = (
            ["Показатель", "Ед. изм.", "Код ОКЕИ"]
            + [_period_label(p) for p in periods]
            + ["Всего"]
        )
        keys = (
            ["indicator", "measure", "code"]
            + [f"m_{_period_col_key(p)}" for p in periods]
            + ["total"]
        )
        groups: List[tuple] = []

        def fill_cells(row, section_key, code, ind_name):
            inner = agg.get((section_key, ind_name))
            total = Decimal("0")
            for period in periods:
                val = inner.get(period, Decimal("0")) if inner is not None else Decimal("0")
                row[f"m_{_period_col_key(period)}"] = _dec_to_float(val)
                total += val
            row["total"] = _dec_to_float(total)

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
                "months": _period_count(periods),
                "records": n_records,
            },
        }

    def _load_pivot_ga15_empty(self, message: str) -> Dict[str, Any]:
        """Таблица 15-ГА без выбранного аэропорта."""
        row = {k: None for k in GA15_KEYS}
        row[GA15_KEYS[0]] = message
        return {
            "rows": [row],
            "headers": GA15_FLAT_HEADERS,
            "keys": GA15_KEYS,
            "groups": GA15_HEADER_GROUPS,
            "stats": {
                "airport_name": "",
                "layout_ga15": True,
                "records": 0,
                "indicators": 0,
            },
        }

    def _load_pivot_ga15_airport(self, filters: ReportFilters, airport_id: int) -> Dict[str, Any]:
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
            canon = GA15_CODE_ALIASES.get(code, code)
            agg[canon] = agg.get(canon, Decimal("0")) + _aggregate_total(row)

        airport_name = ""
        with get_session() as session:
            ap = session.get(Airport, airport_id)
            airport_name = ap.name.strip() if ap else ""

        period_label = _period_label_ru(filters)
        pivot_rows: List[Dict[str, Any]] = []

        for spec in GA15_TABLE_ROWS:
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
                        total, found = _ga15_sum_metric(agg, rc, tag)
                        row[GA15_KEYS[ci]] = _dec_to_float(total) if found else 0.0
            pivot_rows.append(row)

        n_data_lines = sum(
            1 for s in GA15_TABLE_ROWS if s.kind in ("data", "subdetail") and s.row_code
        )

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

    def load_detail_data(self, mode: int, filters: ReportFilters) -> Dict[str, Any]:
        """Загружает данные для подробной таблицы"""
        if mode == 1:  # MODE_AIRLINE
            # Регулярность выводится рядом с типом маршрута: вдвоём они и образуют
            # рейс. Без неё две записи с одним показателем, месяцем и типом
            # маршрута выглядели в таблице одинаково — а удаляют именно отсюда,
            # и отменить удаление нечем (FUNC-11).
            headers = [
                "ID", "Авиакомпания", "Код а/к", "Показатель", "Месяц", "Год",
                "Значение", "Ед. изм.", "Тип маршрута", "Регулярность",
            ]
            # Поля снимка строки (services/detail_rows.py), а не пути по связям
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