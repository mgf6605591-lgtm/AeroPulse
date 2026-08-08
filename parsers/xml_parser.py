# parsers/xml_parser.py
"""
Импорт XML формы 12-ГА (Rosstat): отчётный файл как в примере 0615106_012_012_*.xml,
метаданные колонок/строк — f12.xml (metaForm).

Колонки XML code → тип маршрута в БД:
  4, 5 → международные (trunk), в БД сохраняется сумма;
  6    → внутренние всего (local);
  7    → из них местные (interregional);
  8    → из них субсидируемые (subsidir);
  9    → ИТОГО гр.4+гр.5+гр.6 (производное), в импорт не включается.

Строки XML code → показатель, единица измерения и раздел бланка — из общей
таблицы `utils/ga12_layout.py`, той же, по которой разбирается XLSX.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any, Dict, List, Optional

from parsers.base_parser import BaseParser
from utils.ga12_layout import GA12_ROW_BY_XML_ROW
from utils.months import month_from_meta_filename, month_from_period

# Коды строк, названия, единицы измерения и раздел — из общей таблицы бланка
# (utils/ga12_layout.py). Своя копия карты строк здесь и раскладка по индексам
# листа в XLSX-парсере разошлись, и один отчёт в двух форматах давал в базе
# разный набор строк (BUG-3).


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

        month_res = month or month_from_period(period) or month_from_meta_filename(file_name)
        year_res = year if year is not None else file_year
        # Заглушек «январь 2025» здесь нет: неопределённый период возвращается как None,
        # решение принимает вызывающий код (DATA-2).

        indicators = cls._extract_indicators(root)

        for ind in indicators:
            ind["airline_name"] = airline_name
            ind["entity_type"] = entity_type or "airline"
            ind["entity_id"] = entity_id

        return {
            "entity_type": entity_type or "airline",
            "entity_id": entity_id,
            "airline": {
                "name": airline_name,
                "id": entity_id,
            },
            "month": month_res,
            "year": year_res,
            "indicators": indicators,
            "data_type": "airline",
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
            blank_row = GA12_ROW_BY_XML_ROW.get(rcode)
            if blank_row is None:
                continue

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
                entries.append(("trunk", s))

            if v6 is not None:
                entries.append(("local", v6))
            if v7 is not None:
                entries.append(("interregional", v7))
            if v8 is not None:
                entries.append(("subsidir", v8))

            for route_type, value in entries:
                if value is None:
                    continue
                out.append(
                    {
                        "indicator_code": blank_row.code,
                        "indicator_name": blank_row.name,
                        "measure": blank_row.measure,
                        "route_type": route_type,
                        "regularity": blank_row.section,
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
