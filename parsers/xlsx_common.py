# parsers/xlsx_common.py
"""Общие приёмы разбора книг Excel: нормализация содержимого листа и поиск листа формы.

Оба XLSX-парсера (12-ГА и 15-ГА) ищут свой лист по содержимому, а не по позиции в
книге. Прежний молчаливый откат на первый лист приводил к тому, что вместо отчёта
разбирался титульный лист: показателей там нет, импорт давал ноль записей и при этом
сообщал об успехе (DATA-4).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

import pandas as pd


def sheet_text(df: pd.DataFrame) -> str:
    """Всё содержимое листа одной нормализованной строкой."""
    values = (
        str(v)
        for v in df.to_numpy().ravel()
        if v is not None and not (isinstance(v, float) and pd.isna(v))
    )
    return re.sub(r"\s+", " ", " ".join(values)).lower().replace("ё", "е")


def count_markers(df: pd.DataFrame, markers: Iterable[str]) -> int:
    """Сколько признаков формы встретилось на листе."""
    text = sheet_text(df)
    return sum(1 for marker in markers if marker in text)


def sheet_names(file_name: str) -> list[str]:
    with pd.ExcelFile(file_name) as xl:
        return [str(name) for name in xl.sheet_names]


def find_sheet(
    file_name: str,
    looks_like: Callable[[pd.DataFrame], bool],
    name_hint: Callable[[str], bool] | None = None,
) -> tuple[pd.DataFrame | None, str | None]:
    """Первый лист книги, прошедший проверку по содержимому, вместе с его именем.

    Имя листа влияет только на порядок перебора: лист с подходящим именем, но без
    нужного содержимого, бланком не считается — иначе достаточно было бы переименовать
    лист, чтобы отчёт разобрался по чужой раскладке.
    """
    with pd.ExcelFile(file_name) as xl:
        hinted = [n for n in xl.sheet_names if name_hint and name_hint(str(n))]
        rest = [n for n in xl.sheet_names if n not in hinted]
        for name in hinted + rest:
            df = xl.parse(sheet_name=name, header=None)
            if looks_like(df):
                return df, str(name)
    return None, None
