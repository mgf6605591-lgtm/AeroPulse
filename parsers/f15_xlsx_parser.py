# parsers/f15_xlsx_parser.py
"""
Импорт XLSX отчёта 15-ГА (аэропорты).

Раскладка листа данных повторяет XML-выгрузку той же формы:
  графа 2 (индекс 1)      — № строки 1…9, он же код строки XML, делённый на 10;
  графы 3…13 (индексы 2…12) — ВС, пассажиры, груз, почта.

Коды, названия и единицы измерения показателей берутся из `f15_xml_parser`: один и
тот же отчёт, присланный в XLSX и в XML, должен давать в базе одинаковый набор строк,
иначе своды по разным предприятиям становятся несопоставимыми.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from parsers.base_parser import BaseParser
from parsers.f15_xml_parser import (
    F15_COL_TITLES,
    F15_COL_TO_METRIC,
    F15_ROW_TITLES,
    F15_XML_ROW_TO_RC,
    F15XMLParser,
)
from parsers.xlsx_common import count_markers, find_sheet, sheet_names

# Подписи строк бланка, по которым лист опознаётся как 15-ГА. Требуется несколько
# сразу — отдельная подпись встречается и в сопроводительных текстах.
F15_SHEET_MARKERS = (
    "международные регулярные",
    "международные нерегулярные",
    "внутренние регулярные",
    "внутренние нерегулярные",
    "коммерческие перевозки",
    "все прочие операции",
)
F15_SHEET_MARKERS_REQUIRED = 4

# Графа 1 бланка — вид перевозок, графа 2 — номер строки.
ROW_TITLE_COL = 0
ROW_NUMBER_COL = 1

# Отчётный период листа данных: «за __февраль_2026__г.».
# Читается только отсюда — из того же листа, откуда берутся цифры, поэтому не может
# разойтись с ними, если бланк заполняли копированием прошлого месяца (DATA-3).
PERIOD_CELL: Tuple[int, int] = (6, 0)

# Название аэропорта: «Наименование аэропорта:  ФКП "Аэропорты Севера"».
AIRPORT_NAME_CELL: Tuple[int, int] = (0, 0)


class F15XLSXParser(BaseParser):
    """Парсер XLSX отчёта 15-ГА → AirportIndicators (коды 15ГА-Rxx-МЕТРИКА)."""

    @classmethod
    def parse_file(cls, file_name: str, month: Optional[str] = None, year: Optional[int] = None,
                   entity_type: Optional[str] = None, entity_id: Optional[int] = None,
                   entity_name: Optional[str] = None) -> Dict:
        df, sheet_name = cls._read_f15_sheet(file_name)

        # Период: явные параметры вызова > ячейка листа данных. Заглушек нет —
        # неопределённый период уходит наверх как None (DATA-2).
        cell_month, cell_year = cls._period_from_df(df)
        month = month or cell_month
        year = year if year is not None else cell_year

        airport_name = entity_name.strip() if entity_name else cls._airport_name_from_df(df)

        return {
            "data_type": "airport",
            "entity_type": entity_type or "airport",
            "entity_id": entity_id,
            "sheet_name": sheet_name,
            "airport": {
                "name": airport_name,
                "id": entity_id,
            },
            "month": month,
            "year": year,
            "indicators": cls._extract_indicators(df),
        }

    @classmethod
    def is_f15_workbook(cls, file_name: str) -> bool:
        """Есть ли в книге лист формы 15-ГА. Используется для выбора парсера."""
        df, _ = find_sheet(file_name, cls._looks_like_f15, cls._name_hints_f15)
        return df is not None

    @classmethod
    def _looks_like_f15(cls, df: pd.DataFrame) -> bool:
        return count_markers(df, F15_SHEET_MARKERS) >= F15_SHEET_MARKERS_REQUIRED

    @staticmethod
    def _name_hints_f15(sheet_name: str) -> bool:
        n = str(sheet_name).upper().replace(" ", "").replace("-", "")
        return "15ГА" in n or "ГА15" in n

    @classmethod
    def _read_f15_sheet(cls, file_name: str) -> Tuple[pd.DataFrame, str]:
        """Лист данных 15-ГА вместе с его именем.

        Лист шапки («Шапка15ГА») подходит по имени, но не по содержимому: подписей
        строк бланка на нём нет, поэтому листом данных он не станет.
        """
        df, name = find_sheet(file_name, cls._looks_like_f15, cls._name_hints_f15)
        if df is None:
            raise ValueError(
                "Не удалось распознать форму: ни на одном листе книги "
                f"({', '.join(sheet_names(file_name))}) нет строк бланка 15-ГА."
            )
        return df, name

    @classmethod
    def _period_from_df(cls, df: pd.DataFrame) -> Tuple[Optional[str], Optional[int]]:
        row, col = PERIOD_CELL
        if df.shape[0] <= row or df.shape[1] <= col:
            return None, None
        # Разбор значения общий с 12-ГА: формулировка «за __февраль_2026__г.»
        # раскладывается на месяц и год теми же правилами.
        from parsers.xlsx_parser import XLSXParser

        return XLSXParser._parse_month_year_value(df.iloc[row, col])

    @classmethod
    def _airport_name_from_df(cls, df: pd.DataFrame) -> str:
        row, col = AIRPORT_NAME_CELL
        if df.shape[0] <= row or df.shape[1] <= col:
            return ""
        raw = df.iloc[row, col]
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return ""
        text = str(raw).strip()
        # «Наименование аэропорта:  ФКП "Аэропорты Севера"» → всё после двоеточия.
        if ":" in text:
            text = text.split(":", 1)[1]
        return text.strip()

    @classmethod
    def _extract_indicators(cls, df: pd.DataFrame) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if df.shape[1] <= ROW_NUMBER_COL:
            return out

        for r in range(df.shape[0]):
            row_number = cls._row_number(df.iloc[r, ROW_NUMBER_COL])
            if row_number is None:
                continue
            if not cls._is_data_row(df.iloc[r, ROW_TITLE_COL]):
                continue
            rcode = row_number * 10
            rc = F15_XML_ROW_TO_RC.get(rcode)
            if not rc:
                continue

            row_title = F15_ROW_TITLES.get(rcode, f"Строка {rcode}")

            for ccode, tag in F15_COL_TO_METRIC.items():
                col_index = int(ccode) - 1
                if col_index >= df.shape[1]:
                    continue
                value = cls._cell_decimal(df.iloc[r, col_index])
                if value is None:
                    continue

                out.append(
                    {
                        "indicator_code": f"15ГА-{rc}-{tag}",
                        "indicator_name": f"{row_title} — {F15_COL_TITLES.get(ccode, ccode)}",
                        "measure": F15XMLParser._measure_for_col(ccode),
                        "value": value,
                    }
                )

        return out

    @staticmethod
    def _is_data_row(raw) -> bool:
        """Строка данных названа видом перевозок; строка нумерации граф — нет.

        Под шапкой бланка идёт служебная строка «1|2|3|…|13», нумерующая графы.
        В её графе 2 стоит число 2, и по одному лишь номеру она неотличима от
        строки 02 «Международные нерегулярные»: числа 3…13 попадали в базу как
        показатели этой строки, а настоящая строка 02 затем часть из них
        перезаписывала. Признак — вид перевозок словами, а не цифра.
        """
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return False
        text = str(raw).strip()
        if not text:
            return False
        return not text.replace(",", ".").replace(".", "").isdigit()

    @staticmethod
    def _row_number(raw) -> Optional[int]:
        """Номер строки бланка (1…9) из графы 2, иначе None."""
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or isinstance(raw, bool):
            return None
        try:
            number = int(str(raw).strip().replace(",", ".").split(".")[0])
        except (TypeError, ValueError):
            return None
        return number if 1 <= number <= 9 else None

    @staticmethod
    def _cell_decimal(raw) -> Optional[Decimal]:
        """Значение ячейки. Прочерки и «Х» в незаполняемых графах — не значения."""
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return None
        return F15XMLParser._parse_cell_value(str(raw))
