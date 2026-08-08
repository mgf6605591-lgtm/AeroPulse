# utils/months.py
"""Месяц отчётного периода: один источник вместо копий в каждом парсере (ARCH-8).

Список названий месяцев был выписан заново в каждом из трёх парсеров
(`_MONTH_ENUM`), а разбор номера месяца — из атрибута `period` в корне XML и из
имени файла — дословно повторён в двух разборщиках XML. Семь определений одного
и того же: любая правка требовала найти их все, а разойтись они могли молча.

Названия берутся из перечисления `Months` — того самого, в котором месяц
хранится в базе. Так список не может разойтись со схемой: он и есть схема.
"""
import re
from typing import Optional

from db.models.enums import Months

# Названия месяцев в порядке номеров 1…12 — это порядок объявления в `Months`.
MONTH_NAMES = tuple(month.name for month in Months)

# Номер месяца в имени файла метаданных: «..._2025_02_...».
_FILENAME_PERIOD = re.compile(r"_(\d{4})_(\d{2})_")


def month_name(number: int) -> Optional[str]:
    """Название месяца по номеру 1…12 или None, если номер вне диапазона."""
    if not isinstance(number, int) or not 1 <= number <= len(MONTH_NAMES):
        return None
    return MONTH_NAMES[number - 1]


def month_from_period(period: str) -> Optional[str]:
    """Месяц из атрибута `period` в корне XML: последние две цифры — номер 01…12."""
    if not period or not str(period).strip().isdigit():
        return None
    digits = str(period).strip()
    if len(digits) < 2:
        return None
    return month_name(int(digits[-2:]))


def month_from_meta_filename(path: str) -> Optional[str]:
    """Резерв: месяц из имени файла вида `_ГГГГ_ММ_`."""
    found = _FILENAME_PERIOD.search(str(path).replace("\\", "/"))
    return month_name(int(found.group(2))) if found else None
