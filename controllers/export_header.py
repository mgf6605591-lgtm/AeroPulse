# controllers/export_header.py
"""Шапка выгружаемой книги: что это за отчёт (FUNC-4).

В файл уходили только заголовки колонок и цифры. Название предприятия, период и
число показателей были видны на экране, но в книгу не переносились, а лист
назывался «Данные». Выгруженный отчёт получался обезличенным: определить по нему
авиакомпанию и период было нельзя, и две выгрузки различались разве что именем
файла, которое пользователь задавал вручную. Вместе с DATA-1, где колонки
подписаны месяцем без года, файл переставал читаться вне того сеанса, в котором
его сделали.

Шапка собирается здесь, а не в самом экспорте: это описание отчёта, а не работа
с книгой, и проверять его можно без Qt и без openpyxl.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from controllers.report_filters import NO_FILTERS
from utils.constants import MODE_AIRLINE, MONTHS_LIST, MONTHS_RU, VIEW_DETAIL

# Excel запрещает в названии листа : \ / ? * [ ] и больше 31 символа.
SHEET_TITLE_LIMIT = 31


@dataclass(frozen=True)
class ExportHeader:
    """Название листа и строки шапки — пары «подпись, значение»."""

    sheet_title: str
    lines: list[tuple[str, str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.lines)


def form_name(mode: int) -> str:
    return "12-ГА" if mode == MODE_AIRLINE else "15-ГА"


def month_label(number: int | None) -> str:
    """Название месяца по его номеру 1…12."""
    if not number or not 1 <= number <= len(MONTHS_LIST):
        return ""
    return MONTHS_RU[MONTHS_LIST[number - 1]]


def period_label(filters) -> str:
    """«Январь 2025» или «Январь 2025 — Март 2025»; пусто, если период не задан."""
    period = getattr(filters, "period", None)
    if period is None:
        return ""
    start, end = period

    def one(period) -> str:
        year, month = period
        name = month_label(month)
        return f"{name} {year}".strip() if name else str(year)

    first, last = one(start), one(end)
    return first if first == last else f"{first} — {last}"


def entity_label(mode: int, stats: dict[str, Any]) -> str:
    """Предприятие или пометка о своде, если их несколько."""
    name = (stats.get("airline_name") or stats.get("airport_name") or "").strip()
    if name:
        return name
    return "свод по всем авиакомпаниям" if mode == MODE_AIRLINE else "свод по всем аэропортам"


def build_export_header(
    *,
    mode: int,
    view: str,
    filters=None,
    stats: dict[str, Any] | None = None,
    user: str | None = None,
    now: datetime | None = None,
) -> ExportHeader:
    """Собирает шапку. Пустые значения в неё не попадают.

    Момент выгрузки передаётся снаружи, а не берётся здесь: иначе содержимое
    книги зависело бы от часов, и проверить его было бы нечем.
    """
    filters = filters if filters is not None else NO_FILTERS
    stats = stats or {}
    now = now or datetime.now()

    form = form_name(mode)
    view_name = "подробная таблица" if view == VIEW_DETAIL else "свод"

    lines: list[tuple[str, str]] = [
        ("Форма", form),
        ("Предприятие", entity_label(mode, stats)),
    ]

    period = period_label(filters)
    if period:
        lines.append(("Период", period))

    # Счётчики — те же, что показывает строка под таблицей: выгрузка и экран
    # должны рассказывать об отчёте одно и то же.
    if stats.get("indicators"):
        lines.append(("Показателей", str(stats["indicators"])))
    if stats.get("records"):
        lines.append(("Записей", str(stats["records"])))

    lines.append(("Представление", view_name))
    lines.append(("Выгружено", now.strftime("%d.%m.%Y %H:%M")))
    if user:
        lines.append(("Пользователь", str(user)))

    title = f"{form} ({view_name})"
    return ExportHeader(sheet_title=title[:SHEET_TITLE_LIMIT], lines=lines)
