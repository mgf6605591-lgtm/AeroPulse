# utils/ga15_summary_layout.py
"""Свод по всем аэропортам: раскладка листа «15-ГА» из годовой сводки.

Строка — аэропорт, колонки — периоды, в каждом по одиннадцати графам бланка.
Периоды идут как в самой сводке: три месяца, квартал, снова три месяца, квартал,
полугодие — и так до «12 месяцев». Квартал и нарастающий итог показываются
только тогда, когда все их месяцы попали в выбранный период: сумма за неполный
квартал выглядела бы кварталом и молча занижала бы отчёт.

Ячейка берётся из строки 08 бланка — «Коммерческие перевозки — всего». Именно её
и сводит годовая сводка: строка «Все прочие операции» в итоги не входит, а во
внутренних перевозках строка 08 совпадает со строкой 07 «Внутренние — всего».
"""
from typing import Dict, List, Sequence, Tuple

from utils.constants import MONTHS_RU, MONTHS_LIST

# Строка бланка, из которой берутся цифры сводки.
GA15_SUMMARY_ROW_CODE = "R08"

# Подписи одиннадцати граф. Уровней заголовка два — период и графа, — поэтому
# группа бланка («ПАССАЖИРЫ», «ГРУЗ», «ПОЧТА») входит в подпись самой графы.
GA15_SUMMARY_METRIC_HEADERS: Tuple[str, ...] = (
    "ВС, ед.",
    "Пасс. отправл.",
    "Пасс. принят.",
    "Пасс. всего",
    "Пасс. транзит",
    "Груз отгр., т",
    "Груз разгр., т",
    "Груз всего, т",
    "Почта отгр., т",
    "Почта разгр., т",
    "Почта всего, т",
)

# Первая колонка листа.
GA15_SUMMARY_ENTITY_HEADER = "Аэропорт"
GA15_SUMMARY_ENTITY_KEY = "airport"

# Строка «Итого» сводки: складываются только предприятия. Аэропорты, входящие в
# предприятие, показаны разбивкой под ним, и в итог они уже вошли — его строкой.
GA15_SUMMARY_TOTAL_TITLE = "Итого:"

# Отступ, которым разбивка отличается от предприятия.
GA15_SUMMARY_CHILD_INDENT = "    "

# Нарастающие итоги сводки: месяц, на котором итог закрывается → его подпись.
CUMULATIVE_AT_MONTH: Dict[int, str] = {
    6: "6 месяцев",
    9: "9 месяцев",
    12: "12 месяцев",
}


class Ga15PeriodBlock:
    """Колонка-период сводки: месяц, квартал или нарастающий итог."""

    __slots__ = ("key", "label", "months")

    def __init__(self, key: str, label: str, months: Tuple[Tuple[int, int], ...]):
        self.key = key
        self.label = label
        # Месяцы, которые складываются в этот блок: пары (год, номер месяца).
        self.months = months

    def __repr__(self) -> str:  # для читаемых сообщений в тестах
        return f"Ga15PeriodBlock({self.key!r}, {self.label!r}, {self.months!r})"


def month_label(year: int, month: int) -> str:
    """«Январь 2025». Год указывается всегда, а не подразумевается заголовком."""
    key = MONTHS_LIST[month - 1]
    return f"{MONTHS_RU[key]} {year}"


def summary_period_blocks(months: Sequence[Tuple[int, int]]) -> List[Ga15PeriodBlock]:
    """Колонки сводки по списку месяцев периода (пары «год, номер месяца»).

    Порядок — как в годовой сводке: месяцы подряд, после третьего месяца
    квартала его итог, а после второго, третьего и четвёртого кварталов — ещё и
    нарастающий итог с начала года.
    """
    ordered = sorted(set(months))
    present = set(ordered)
    blocks: List[Ga15PeriodBlock] = []

    for year, month in ordered:
        blocks.append(
            Ga15PeriodBlock(f"m{year}_{month}", month_label(year, month), ((year, month),))
        )

        if month % 3:
            continue

        quarter = month // 3
        quarter_months = tuple((year, m) for m in range(month - 2, month + 1))
        if all(m in present for m in quarter_months):
            blocks.append(
                Ga15PeriodBlock(
                    f"q{year}_{quarter}", f"{quarter} квартал {year}", quarter_months
                )
            )

        cumulative = CUMULATIVE_AT_MONTH.get(month)
        if not cumulative:
            continue
        from_january = tuple((year, m) for m in range(1, month + 1))
        if all(m in present for m in from_january):
            blocks.append(
                Ga15PeriodBlock(
                    f"c{year}_{month}", f"{cumulative} {year}", from_january
                )
            )

    return blocks


def summary_columns(blocks: Sequence[Ga15PeriodBlock], metric_tags: Sequence[str]):
    """Заголовки, ключи и группы заголовка для сводки.

    Возвращает (headers, keys, groups); groups — тройки (первая колонка,
    последняя, подпись периода) для двухуровневого заголовка таблицы.
    """
    headers: List[str] = [GA15_SUMMARY_ENTITY_HEADER]
    keys: List[str] = [GA15_SUMMARY_ENTITY_KEY]
    groups: List[Tuple[int, int, str]] = []

    for block in blocks:
        first = len(headers)
        for header, tag in zip(GA15_SUMMARY_METRIC_HEADERS, metric_tags, strict=True):
            headers.append(header)
            keys.append(f"{block.key}_{tag}")
        groups.append((first, len(headers) - 1, block.label))

    return headers, keys, groups
