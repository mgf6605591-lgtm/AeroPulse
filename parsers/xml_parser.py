# parsers/xml_parser.py
"""
Импорт XML формы 12-ГА (Rosstat): отчётный файл как в примере 0615106_012_012_*.xml,
метаданные колонок/строк — f12.xml (metaForm).

Колонки XML code → тип маршрута в БД:
  4, 5 → международные (trunk), в БД сохраняется сумма;
  6    → внутренние всего (local);
  7    → местные (interregional);
  8    → субсидируемые (subsidir);
  9    → итого (производное), в импорт не включается.

Строки XML code → показатель и регулярность — как в типовой форме (см. f12.xml <rows>).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from parsers.base_parser import BaseParser

_MONTH_ENUM = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# XML row code → (код ОКЕИ, название, ед. изм., regularity: regular | irregular | non_commercial)
_XML_ROW_MAP: Dict[int, Tuple[str, str, str, str]] = {
    # Регулярные коммерческие (секция после заголовка строки 1)
    2: ("965", "Самолето-километры", "тыс.сам.-км", "regular"),
    3: ("642", "Отправлений воздушных судов", "ед.", "regular"),
    4: ("356", "Налет часов", "час.", "regular"),
    5: ("792", "Перевезено пассажиров", "чел.", "regular"),
    6: ("168", "Перевезено грузов", "тонн", "regular"),
    7: ("168п", "Перевезено почты", "тонн", "regular"),
    8: ("423", "Выполненный пассажирооборот", "тыс.пасс.-км", "regular"),
    9: ("423п", "Предельный пассажирооборот", "тыс.пасс.-км", "regular"),
    10: ("450", "Выполненный тоннокилометраж", "тыс. ткм", "regular"),
    12: ("450пас", "      а) пассажирский", "тыс. ткм", "regular"),
    13: ("450гр", "      б) грузовой (вкл. срочный груз)", "тыс. ткм", "regular"),
    14: ("450пч", "      в) почтовый", "тыс. ткм", "regular"),
    15: ("450п", "Предельный тоннокилометраж", "тыс. ткм", "regular"),
    # Нерегулярные коммерческие
    17: ("965н", "Самолето-километры", "тыс.сам.-км", "irregular"),
    18: ("642н", "Отправлений воздушных судов", "ед.", "irregular"),
    19: ("356н", "Налет часов", "час.", "irregular"),
    20: ("792н", "Перевезено пассажиров", "чел.", "irregular"),
    21: ("168н", "Перевезено грузов и почты", "тонн", "irregular"),
    22: ("423н", "Выполненный пассажирооборот", "тыс.пасс.-км", "irregular"),
    23: ("423нп", "Предельный пассажирооборот", "тыс.пасс.-км", "irregular"),
    24: ("450н", "Выполненный тоннокилометраж", "тыс. ткм", "irregular"),
    25: ("450нп", "Предельный тоннокилометраж", "тыс. ткм", "irregular"),
    # Некоммерческие полёты (в короткой схеме может быть только часть строк)
    27: ("356нк", "Налет часов", "час.", "non_commercial"),
}


class XMLParser(BaseParser):
    """Парсер XML отчёта 12-ГА для импорта в ту же модель, что и XLSX."""

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

        year_attr = root.get("year")
        try:
            file_year = int(year_attr) if year_attr else None
        except ValueError:
            file_year = None

        period = root.get("period") or ""

        org_name = ""
        for item in root.findall(".//title/item"):
            if item.get("name") == "name":
                raw = item.get("value") or ""
                org_name = raw.replace("&quot;", '"').strip()
                break

        if entity_name:
            airline_name = entity_name.strip()
        elif org_name:
            airline_name = org_name
        else:
            airline_name = ""

        airline_code = airline_name[:3].upper() if airline_name else "UNK"

        month_res = month or cls._month_from_period(period) or cls._month_from_meta_filename(file_name)
        year_res = year if year is not None else file_year
        if not month_res:
            month_res = "January"
        if not year_res:
            year_res = 2025

        indicators = cls._extract_indicators(root)

        for ind in indicators:
            ind["airline_name"] = airline_name
            ind["airline_code"] = airline_code
            ind["entity_type"] = entity_type or "airline"
            ind["entity_id"] = entity_id

        return {
            "entity_type": entity_type or "airline",
            "entity_id": entity_id,
            "airline": {
                "name": airline_name,
                "code": airline_code,
                "id": entity_id,
            },
            "month": month_res,
            "year": year_res,
            "indicators": indicators,
            "data_type": "airline",
        }

    @classmethod
    def _month_from_period(cls, period: str) -> Optional[str]:
        """
        Атрибут period у корня XML: последние две цифры — номер месяца 01–12.
        """
        if not period or not period.strip().isdigit():
            return None
        p = period.strip()
        if len(p) >= 2:
            m = int(p[-2:])
            if 1 <= m <= 12:
                return _MONTH_ENUM[m - 1]
        return None

    @classmethod
    def _month_from_meta_filename(cls, path: str) -> Optional[str]:
        """Резерв: если в имени файла есть _YYYY_MM_."""
        import re

        m = re.search(r"_(\d{4})_(\d{2})_", path.replace("\\", "/"))
        if m:
            mi = int(m.group(2))
            if 1 <= mi <= 12:
                return _MONTH_ENUM[mi - 1]
        return None

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
            if rcode not in _XML_ROW_MAP:
                continue

            okei, name, measure, regularity = _XML_ROW_MAP[rcode]
            cols: Dict[str, str] = {}
            for col in row.findall("col"):
                c = col.get("code")
                if c is not None and col.text is not None:
                    cols[c] = col.text.strip()

            # Столбец 9 — контрольное итого, не грузим в БД (избегаем дубля с сырыми колонками)
            v4 = cls._parse_decimal(cols.get("4"))
            v5 = cls._parse_decimal(cols.get("5"))
            v6 = cls._parse_decimal(cols.get("6"))
            v7 = cls._parse_decimal(cols.get("7"))
            v8 = cls._parse_decimal(cols.get("8"))

            entries = []

            if v4 is not None or v5 is not None:
                s = Decimal("0")
                if v4 is not None:
                    s += v4
                if v5 is not None:
                    s += v5
                entries.append(("trunk", float(s)))

            if v6 is not None:
                entries.append(("local", float(v6)))
            if v7 is not None:
                entries.append(("interregional", float(v7)))
            if v8 is not None:
                entries.append(("subsidir", float(v8)))

            for route_type, value in entries:
                if value is None:
                    continue
                out.append(
                    {
                        "indicator_code": okei,
                        "indicator_name": name.strip(),
                        "measure": measure.strip(),
                        "route_type": route_type,
                        "regularity": regularity,
                        "value": value,
                    }
                )

        return out

    @classmethod
    def _parse_decimal(cls, text: Optional[str]) -> Optional[Decimal]:
        if text is None or text == "":
            return None
        t = text.strip().replace(",", ".")
        try:
            return Decimal(t)
        except Exception:
            return None
