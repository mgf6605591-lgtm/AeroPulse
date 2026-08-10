"""Показатель формы 15-ГА: код графы и отбор по нему.

Показатель здесь — не строка и не графа, а их пересечение (`15ГА-R01-ПАС_ОТП`),
поэтому и отбор решается по ячейке, а не по строке (FUNC-7). Общее двум сводам:
и сводка по всем аэропортам, и бланк одного считают код графы одинаково — иначе
одна и та же галочка в фильтре означала бы в них разное.
"""
import re

from controllers.report_filters import NO_FILTERS, ReportFilters
from db.models.entities import Indicator
from utils.ga15_airport_layout import GA15_METRIC_TAGS, GA15_TABLE_ROWS, Ga15RowSpec

# Псевдонимы кода показателя → канонический код вида 15ГА-R05-ПАС_ОТП
CODE_ALIASES: dict[str, str] = {}


def metric_code_candidates(row_code: str, tag: str) -> list[str]:
    keys = [f"15ГА-{row_code}-{tag}"]
    if re.fullmatch(r"R\d{2}", row_code):
        n = int(row_code[1:])
        keys.append(f"15ГА-{n:02d}-{tag}")
    return keys


def selected_codes(session, filters: ReportFilters | None) -> set[str] | None:
    """Коды выбранных показателей. None — отбора нет, показывать бланк целиком.

    Фильтр хранит id, а бланк 15-ГА собирается по кодам, поэтому перевод нужен
    здесь: по агрегату его не сделать — показателя, выбранного в фильтре, может
    не оказаться ни в одной записи, и такая графа должна показывать ноль, а не
    прочерк.
    """
    ids = (filters or NO_FILTERS).indicator_ids
    if not ids:
        return None
    rows = session.query(Indicator.code).filter(Indicator.id.in_(ids)).all()
    codes = {(code or "").strip() for (code,) in rows}
    return {CODE_ALIASES.get(code, code) for code in codes if code}


def metric_in_filter(selected: set[str] | None, row_code: str, tag: str) -> bool:
    """Попадает ли графа строки бланка в отбор показателей."""
    if selected is None:
        return True
    return any(key in selected for key in metric_code_candidates(row_code, tag))


def _row_in_filter(spec: Ga15RowSpec, selected: set[str] | None) -> bool:
    """Осталась ли у строки бланка хоть одна заполняемая графа в отборе.

    Графы с «Х» не считаются: они не заполняются в самом бланке, и строка,
    от которой остались только они, не показывает ничего.
    """
    if selected is None or not spec.row_code:
        return True
    return any(
        metric_in_filter(selected, spec.row_code, tag)
        for tag in GA15_METRIC_TAGS
        if tag not in spec.not_filled
    )


def specs_in_filter(selected: set[str] | None) -> list[Ga15RowSpec]:
    """Строки бланка, остающиеся на экране при заданном отборе (FUNC-7).

    Заголовок раздела и «в том числе:» держатся на том, что под ними: без
    единой оставшейся строки они превращаются в подпись к пустому месту.
    """
    if selected is None:
        return list(GA15_TABLE_ROWS)

    data_kinds = ("data", "subdetail")
    keep = [
        spec.kind not in data_kinds or _row_in_filter(spec, selected)
        for spec in GA15_TABLE_ROWS
    ]

    for i, spec in enumerate(GA15_TABLE_ROWS):
        if spec.kind not in ("section", "subheading"):
            continue
        # Раздел кончается следующим разделом и держится на любой своей строке.
        # «В том числе:» относится только к идущей за ним детализации, поэтому
        # его закрывает и обычная строка бланка: строка 05 стоит после «в том
        # числе:», но раскрывает не его, а строку 03.
        closes = (
            ("section",) if spec.kind == "section"
            else ("section", "subheading", "data")
        )
        keep[i] = False
        for j in range(i + 1, len(GA15_TABLE_ROWS)):
            following = GA15_TABLE_ROWS[j]
            if following.kind in closes:
                break
            if following.kind in data_kinds and keep[j]:
                keep[i] = True
                break

    return [
        spec for spec, visible in zip(GA15_TABLE_ROWS, keep, strict=True) if visible
    ]
