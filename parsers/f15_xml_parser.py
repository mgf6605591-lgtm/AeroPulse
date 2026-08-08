# parsers/f15_xml_parser.py
"""
Импорт XML отчёта 15-ГА (аэропорты). Метаданные формы — как в типовом f15.xml (metaForm idf="15").

Структура **файла данных** совпадает с 12-ГА: корень с year/period, title, sections/section/row/col.
Отличие — коды строк (10, 20, …, 90) и колонки 3–13 (ВС, пассажиры, груз, почта).

Шаблон-only metaForm без значений в col не является файлом данных.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any, Dict, List, Optional

from parsers.base_parser import BaseParser
from utils.months import month_from_meta_filename, month_from_period

# Код строки XML (f15.xml) → ключ строки в кодах показателей 15ГА-Rxx-...
F15_XML_ROW_TO_RC: Dict[int, str] = {
    10: "R01",
    20: "R02",
    30: "R03",
    40: "R04ИНО",
    50: "R05",
    60: "R06",
    70: "R07",
    80: "R08",
    90: "R09",
}

# Код колонки XML → суффикс кода показателя (как в data_controller / ga15)
F15_COL_TO_METRIC: Dict[str, str] = {
    "3": "ВС",
    "4": "ПАС_ОТП",
    "5": "ПАС_ПРИН",
    "6": "ПАС_ВСЕГО",
    "7": "ПАС_ТРАНЗ",
    "8": "ГР_ОТГР",
    "9": "ГР_РАЗГ",
    "10": "ГР_ВСЕГО",
    "11": "ПЧ_ОТГР",
    "12": "ПЧ_РАЗГ",
    "13": "ПЧ_ВСЕГО",
}

F15_ROW_TITLES: Dict[int, str] = {
    10: "Международные регулярные",
    20: "Международные нерегулярные",
    30: "Международные - всего (стр.01+стр.02)",
    40: "иностранными авиакомпаниями",
    50: "Внутренние регулярные",
    60: "Внутренние нерегулярные",
    70: "Внутренние - всего (стр.05+стр.06)",
    80: "Коммерческие перевозки - всего (стр.03+стр.07)",
    90: "Все прочие операции",
}

F15_COL_TITLES: Dict[str, str] = {
    "3": "Количество ВС, ед.",
    "4": "Пассажиры отправленные, чел.",
    "5": "Пассажиры принятые, чел.",
    "6": "Пассажиры всего (гр.4+гр.5), чел.",
    "7": "Пассажиры прямой транзит, чел.",
    "8": "Груз отгружено, т",
    "9": "Груз разгружено, т",
    "10": "Груз всего (гр.8+гр.9), т",
    "11": "Почта отгружено, т",
    "12": "Почта разгружено, т",
    "13": "Почта всего (гр.11+гр.12), т",
}


class F15XMLParser(BaseParser):
    """Парсер XML отчёта 15-ГА → AirportIndicators (коды 15ГА-Rxx-МЕТРИКА)."""

    @classmethod
    def is_meta_template_only(cls, root: ET.Element) -> bool:
        return root.tag == "metaForm" and root.get("idf") == "15"

    @classmethod
    def is_f15_data(cls, root: ET.Element) -> bool:
        """Отличие от 12-ГА: колонка 3 (ВС) у строк 10…90 и/или блок почты 11–13."""
        if cls.is_meta_template_only(root):
            return False
        f15_row_codes = {str(k) for k in F15_XML_ROW_TO_RC.keys()}
        for row in root.findall(".//sections/section/row"):
            rc = row.get("code")
            col_codes = {c.get("code") for c in row.findall("col") if c.get("code") is not None}
            if not col_codes:
                continue
            if "13" in col_codes:
                return True
            if "11" in col_codes and "12" in col_codes:
                return True
            if rc in f15_row_codes and "3" in col_codes:
                return True
        return False

    @classmethod
    def parse_file(
        cls,
        file_name: str,
        month: Optional[str] = None,
        year: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        tree = ET.parse(file_name)
        root = tree.getroot()
        if cls.is_meta_template_only(root):
            raise ValueError(
                "Этот XML — шаблон метаданных формы 15-ГА (metaForm), а не файл отчёта с данными. "
                "Нужен XML выгрузки отчёта с элементами row/col и заполненными значениями."
            )
        return cls._parse_root(
            root, month, year, entity_type, entity_id, entity_name, file_name
        )

    @classmethod
    def _parse_root(
        cls,
        root: ET.Element,
        month: Optional[str],
        year: Optional[int],
        entity_type: Optional[str],
        entity_id: Optional[int],
        entity_name: Optional[str],
        file_name: str = "",
    ) -> Dict[str, Any]:
        year_attr = root.get("year")
        try:
            file_year = int(year_attr) if year_attr else None
        except ValueError:
            file_year = None

        period = root.get("period") or ""

        org_name = ""
        for item in root.findall(".//title/item"):
            if item.get("name") == "name" or item.get("field") == "name":
                raw = item.get("value") or ""
                org_name = raw.replace("&quot;", '"').strip()
                break

        if entity_name:
            ap_name = entity_name.strip()
        elif org_name:
            ap_name = org_name
        else:
            ap_name = ""

        month_res = month or month_from_period(period) or month_from_meta_filename(file_name)
        year_res = year if year is not None else file_year
        # Заглушек «январь 2025» здесь нет: неопределённый период возвращается как None,
        # решение принимает вызывающий код (DATA-2).

        indicators = cls._extract_indicators(root)

        return {
            "data_type": "airport",
            "entity_type": entity_type or "airport",
            "entity_id": entity_id,
            "airport": {
                "name": ap_name,
                "id": entity_id,
            },
            "month": month_res,
            "year": year_res,
            "indicators": indicators,
        }

    @classmethod
    def _extract_indicators(cls, root: ET.Element) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in root.findall(".//sections/section/row"):
            code_attr = row.get("code")
            if not code_attr:
                continue
            try:
                rcode = int(code_attr)
            except ValueError:
                continue
            rc = F15_XML_ROW_TO_RC.get(rcode)
            if not rc:
                continue

            row_title = F15_ROW_TITLES.get(rcode, row.get("name", "").strip() or f"Строка {rcode}")

            cols: Dict[str, str] = {}
            for col in row.findall("col"):
                c = col.get("code")
                if c is not None and col.text is not None:
                    cols[str(c)] = col.text.strip()

            for ccode, tag in F15_COL_TO_METRIC.items():
                raw = cols.get(ccode)
                val = cls._parse_cell_value(raw)
                if val is None:
                    continue

                icode = f"15ГА-{rc}-{tag}"
                ctitle = F15_COL_TITLES.get(ccode, ccode)
                iname = f"{row_title} — {ctitle}"

                out.append(
                    {
                        "indicator_code": icode,
                        "indicator_name": iname,
                        "measure": cls._measure_for_col(ccode),
                        "value": val,
                    }
                )

        return out

    @classmethod
    def _measure_for_col(cls, ccode: str) -> str:
        if ccode == "3":
            return "ед."
        if ccode in ("4", "5", "6", "7"):
            return "чел."
        return "т"

    @classmethod
    def _parse_cell_value(cls, text: Optional[str]) -> Optional[Decimal]:
        if text is None:
            return None
        t = text.strip()
        if not t:
            return None
        low = t.lower()
        if low in ("х", "x", "-", "—", "n/a"):
            return None
        t = t.replace(",", ".")
        try:
            return Decimal(t)
        except Exception:
            return None
