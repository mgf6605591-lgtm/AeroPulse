# parsers/xlsx_parser.py
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import pandas as pd
from parsers.base_parser import BaseParser
from parsers.xlsx_common import count_markers, find_sheet, sheet_names

_MONTH_ENUM = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Признаки бланка 12-ГА. Подписи взяты из раскладки показателей ниже в этом файле;
# сверить с реальным бланком и при необходимости ужесточить порог — правится здесь,
# в одном месте, не трогая логику разбора.
GA12_SHEET_MARKERS = (
    "самолето-километры",
    "отправлений воздушных судов",
    "налет часов",
    "перевезено пассажиров",
    "выполненный пассажирооборот",
    "выполненный тоннокилометраж",
)
GA12_SHEET_MARKERS_REQUIRED = 4


class XLSXParser(BaseParser):

    @classmethod
    def parse_file(cls, file_name: str, month: str = None, year: int = None,
                   entity_type: str = None, entity_id: int = None, entity_name: str = None) -> Dict:
        """
        Парсинг файла формы ГА12.
        
        Args:
            file_name: путь к файлу
            month: месяц (если не удалось определить из файла)
            year: год (если не удалось определить из файла)
            entity_type: тип предприятия ('airline' или 'airport')
            entity_id: ID предприятия из БД
            entity_name: название предприятия (если не передано через entity_id)
        """
        title_month, title_year = cls._month_year_from_title_sheet(file_name)
        df, sheet_name = cls._read_ga12_sheet(file_name)

        # Используем переданное название предприятия или пытаемся извлечь из файла
        if entity_name:
            airline_name = entity_name
        else:
            # Пробуем извлечь название из файла (резервный вариант)
            try:
                airline_name = df.iloc[2, 9] if not pd.isna(df.iloc[2, 9]) else ""
                if airline_name:
                    airline_name = str(airline_name).strip()
            except Exception:
                airline_name = ""
        
        # Код авиакомпании (генерируем из названия)
        airline_code = airline_name[:3].upper() if airline_name else "UNK"
        
        # Период: явные параметры вызова > лист «Титул» D13. Поиска «где-нибудь в шапке»
        # больше нет: он подхватывал год из реквизитов бланка («приказ Росстата от 2019 г.»)
        # и уводил отчёт в чужой период (DATA-3).
        if not month:
            month = title_month
        if not year:
            year = title_year

        # Заглушки «январь 2025» здесь больше нет: неопределённый период возвращается
        # как None, и решение принимает вызывающий код — молча подставленный период
        # затирал бы через upsert настоящие данные другого месяца (DATA-2).

        # Получаем показатели
        indicators = cls._get_indicators_from_df(df)
        
        # Добавляем информацию о предприятии в каждый показатель
        for indicator in indicators:
            indicator['airline_name'] = airline_name
            indicator['airline_code'] = airline_code
            indicator['entity_type'] = entity_type or 'airline'
            indicator['entity_id'] = entity_id
        
        # Формируем результат
        result = {
            # Форма, распознанная по содержимому файла, а не выбранная пользователем.
            # Раньше XLSX не возвращал data_type вовсе, и проверка расхождения формы
            # в ImportService сравнивала выбор пользователя сам с собой (DATA-6).
            "data_type": "airline",
            "entity_type": entity_type or 'airline',
            "entity_id": entity_id,
            "sheet_name": sheet_name,
            "airline": {
                "name": airline_name,
                "code": airline_code,
                "id": entity_id,
            },
            "month": month,
            "year": year,
            "indicators": indicators,
        }
        
        return result

    @classmethod
    def _find_title_sheet_name(cls, xl: pd.ExcelFile) -> Optional[str]:
        for name in xl.sheet_names:
            n = str(name).strip().lower().replace("ё", "е")
            if n == "титул" or n.startswith("титул"):
                return name
        for name in xl.sheet_names:
            if "титул" in str(name).lower().replace("ё", "е"):
                return name
        return None

    @classmethod
    def _month_year_from_title_sheet(cls, file_name: str) -> Tuple[Optional[str], Optional[int]]:
        """Лист «Титул», ячейка D13 (строка 13, столбец D) — месяц и при наличии год."""
        try:
            with pd.ExcelFile(file_name) as xl:
                sheet = cls._find_title_sheet_name(xl)
                if not sheet:
                    return None, None
                df = xl.parse(sheet_name=sheet, header=None)
            if df.shape[0] < 13 or df.shape[1] < 4:
                return None, None
            raw = df.iloc[12, 3]
            return cls._parse_month_year_value(raw)
        except Exception:
            return None, None

    @classmethod
    def _parse_month_year_value(cls, raw) -> Tuple[Optional[str], Optional[int]]:
        """Преобразует значение D13 в (Months.name, год)."""
        if raw is None:
            return None, None
        if isinstance(raw, float) and pd.isna(raw):
            return None, None

        if isinstance(raw, pd.Timestamp):
            dt = raw.to_pydatetime()
            return cls._month_num_to_name(dt.month), int(dt.year)

        if isinstance(raw, datetime):
            return cls._month_num_to_name(raw.month), int(raw.year)

        # Число: номер месяца 1–12 или серийный номер даты Excel (в т.ч. numpy scalar)
        if not isinstance(raw, bool):
            try:
                x = float(raw)
                if 1 <= x <= 12 and abs(x - round(x)) < 1e-9:
                    return cls._month_num_to_name(int(round(x))), None
                if 20000 < x < 60000:
                    base = datetime(1899, 12, 30)
                    dt = base + timedelta(days=int(x))
                    return cls._month_num_to_name(dt.month), int(dt.year)
            except (TypeError, ValueError):
                pass

        s = str(raw).strip()
        if not s:
            return None, None

        dt_try = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.notna(dt_try):
            dtp = dt_try.to_pydatetime() if hasattr(dt_try, "to_pydatetime") else dt_try
            return cls._month_num_to_name(dtp.month), int(dtp.year)

        year_match = re.findall(r"(20\d{2})", s)
        year = int(year_match[0]) if year_match else None

        month_map = {
            "январ": "January",
            "феврал": "February",
            "март": "March",
            "апрел": "April",
            "мая": "May",
            "май": "May",
            "июн": "June",
            "июл": "July",
            "август": "August",
            "сентябр": "September",
            "октябр": "October",
            "ноябр": "November",
            "декабр": "December",
        }
        low = s.lower()
        for key, month_val in month_map.items():
            if key in low:
                return month_val, year

        m_num = re.match(r"^\s*(\d{1,2})\s*$", s)
        if m_num:
            n = int(m_num.group(1))
            if 1 <= n <= 12:
                return cls._month_num_to_name(n), year

        return None, year

    @staticmethod
    def _month_num_to_name(num: int) -> Optional[str]:
        if 1 <= num <= 12:
            return _MONTH_ENUM[num - 1]
        return None

    @classmethod
    def _looks_like_ga12(cls, df: pd.DataFrame) -> bool:
        """Опознаёт бланк 12-ГА по набору подписей показателей.

        Требуется несколько совпадений сразу: отдельная подпись может встретиться
        и в сопроводительном тексте, а полдесятка — только в самом бланке.
        """
        return count_markers(df, GA12_SHEET_MARKERS) >= GA12_SHEET_MARKERS_REQUIRED

    @classmethod
    def _read_ga12_sheet(cls, file_name: str) -> Tuple[pd.DataFrame, str]:
        """Находит лист формы 12-ГА и возвращает его вместе с именем."""
        df, name = find_sheet(file_name, cls._looks_like_ga12, cls._name_hints_ga12)
        if df is None:
            raise ValueError(
                "Не удалось распознать форму: ни на одном листе книги "
                f"({', '.join(sheet_names(file_name))}) нет показателей бланка 12-ГА."
            )
        return df, name

    @staticmethod
    def _name_hints_ga12(sheet_name: str) -> bool:
        n = str(sheet_name).upper().replace(" ", "").replace("-", "")
        return "ГА12" in n or "12ГА" in n

    @classmethod
    def _get_indicators_from_df(cls, df: pd.DataFrame) -> List[Dict]:
        """Извлечение показателей из DataFrame"""
        indicators = []
        
        # Показатели 12-ГА: номера строк — как в Excel (1-based), в iloc переводим в 0-based.
        # Регулярные: с Excel-строки 11; нерегулярные: с 26; некоммерческие: строка 36 — заголовок, данные с 37.
        regular_rows = [
            (10, '965', 'Самолето-километры', 'тыс.сам.-км'),
            (11, '642', 'Отправлений воздушных судов', 'ед.'),
            (12, '356', 'Налет часов', 'час.'),
            (13, '792', 'Перевезено пассажиров', 'чел.'),
            (14, '168', 'Перевезено грузов', 'тонн'),
            (15, '168п', 'Перевезено почты', 'тонн'),
            (16, '423', 'Выполненный пассажирооборот', 'тыс.пасс.-км'),
            (17, '423п', 'Предельный пассажирооборот', 'тыс.пасс.-км'),
            (18, '450', 'Выполненный тоннокилометраж', 'тыс. ткм'),
            (23, '450п', 'Предельный тоннокилометраж', 'тыс. ткм'),
        ]
        
        irregular_rows = [
            (25, '965н', 'Самолето-километры', 'тыс.сам.-км'),
            (26, '642н', 'Отправлений воздушных судов', 'ед.'),
            (27, '356н', 'Налет часов', 'час.'),
            (28, '792н', 'Перевезено пассажиров', 'чел.'),
            (29, '168н', 'Перевезено грузов и почты', 'тонн'),
            (30, '423н', 'Выполненный пассажирооборот', 'тыс.пасс.-км'),
            (31, '423нп', 'Предельный пассажирооборот', 'тыс.пасс.-км'),
            (32, '450н', 'Выполненный тоннокилометраж', 'тыс. ткм'),
            (33, '450нп', 'Предельный тоннокилометраж', 'тыс. ткм'),
        ]

        non_commercial_rows = [
            (36, '965нк', 'Самолето-километры', 'тыс.сам.-км'),
            (37, '642нк', 'Отправлений воздушных судов', 'ед.'),
            (38, '356нк', 'Налет часов', 'час.'),
            (39, '792нк', 'Перевезено пассажиров', 'чел.'),
            (40, '168нк', 'Перевезено грузов и почты', 'тонн'),
            (41, '423нк', 'Выполненный пассажирооборот', 'тыс.пасс.-км'),
            (42, '423нкп', 'Предельный пассажирооборот', 'тыс.пасс.-км'),
            (43, '450нк', 'Выполненный тоннокилометраж', 'тыс. ткм'),
            (44, '450нкп', 'Предельный тоннокилометраж', 'тыс. ткм'),
        ]
        
        # Столбцы Excel E,F — международные (в сумме trunk); G — внутренние всего (local);
        # H — местные (interregional); I — субсидируемые (subsidir). Индексы 0-based: 4..8.
        route_columns = {
            'international': {
                'cols': [4, 5],
                'sum': True,
                'route_type': 'trunk',
                'regularity': 'regular',
                'name': 'Международные'
            },
            'domestic_total': {
                'cols': [6],
                'sum': False,
                'route_type': 'local',
                'regularity': 'regular',
                'name': 'Внутренние всего'
            },
            'domestic_local': {
                'cols': [7],
                'sum': False,
                'route_type': 'interregional',
                'regularity': 'regular',
                'name': 'Местные'
            },
            'domestic_subsidized': {
                'cols': [8],
                'sum': False,
                'route_type': 'subsidir',
                'regularity': 'regular',
                'name': 'Субсидируемые'
            },
        }
        
        def extract_indicators(row_defs, regularity_override=None):
            for row_idx, code, name, measure in row_defs:
                if row_idx >= len(df):
                    continue
                for route_key, route_info in route_columns.items():
                    try:
                        if route_info.get('sum'):
                            total = Decimal('0')
                            any_cell = False
                            for col in route_info['cols']:
                                if col < df.shape[1]:
                                    v = cls._safe_decimal(df.iloc[row_idx, col])
                                    if v is not None:
                                        any_cell = True
                                        total += v
                            value = total if any_cell else None
                        else:
                            col = route_info['cols'][0]
                            if col < df.shape[1]:
                                value = cls._safe_decimal(df.iloc[row_idx, col])
                            else:
                                value = None
                        
                        if value is None:
                            continue
                        
                        reg = regularity_override if regularity_override else route_info['regularity']
                        
                        indicators.append({
                            'indicator_code': code,
                            'indicator_name': name,
                            'measure': measure,
                            'route_type': route_info['route_type'],
                            'regularity': reg,
                            'value': float(value),
                        })
                    except Exception:
                        continue
        
        extract_indicators(regular_rows, 'regular')
        extract_indicators(irregular_rows, 'irregular')
        extract_indicators(non_commercial_rows, 'non_commercial')
        
        return indicators
    
    @classmethod
    def _safe_decimal(cls, val) -> Optional[Decimal]:
        """Безопасное преобразование значения в Decimal."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        try:
            d = Decimal(str(val))
            if d == 0:
                return Decimal('0')
            return d
        except Exception:
            return None