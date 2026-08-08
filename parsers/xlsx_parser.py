# parsers/xlsx_parser.py
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import pandas as pd
from parsers.base_parser import BaseParser
from parsers.xlsx_common import count_markers, find_sheet, sheet_names
from utils.ga12_layout import (
    GA12_DETAIL_ROW_BY_MARKER,
    GA12_ROW_BY_BLANK_NUMBER,
    Ga12Row,
)
from utils.months import month_name

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

# Графы бланка в индексах листа (0-based): 1 — показатель, 2 — № строки,
# 4 — код по ОКЕИ.
TITLE_COL = 0
ROW_NUMBER_COL = 1
OKEI_COL = 3

# Вид сообщения → графы бланка. Международные хранятся суммой граф 4 и 5;
# графа 9 «ИТОГО» производная и не грузится, иначе она удвоила бы отчёт.
GA12_ROUTE_COLUMNS: Tuple[Tuple[str, Tuple[int, ...]], ...] = (
    ('trunk', (4, 5)),
    ('local', (6,)),
    ('interregional', (7,)),
    ('subsidir', (8,)),
)


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
            return month_name(num)
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
        """Показатели листа 12-ГА: строка бланка опознаётся по своему номеру.

        Раньше строки адресовались жёсткими индексами листа. На настоящем бланке
        они оказались смещены на единицу: индекс первой строки данных указывал на
        заголовок раздела, и каждое значение попадало в базу под кодом следующего
        показателя — самолёто-километры под «Отправлений воздушных судов» и так
        далее по всему бланку. Ни одной ошибки при этом не возникало.

        Теперь ключ — № строки из графы 2 (1…20 сквозь все три раздела), а графа
        «Код по ОКЕИ» служит перекрёстной проверкой. Строки детализации
        тоннокилометража номера не имеют и опознаются маркером «а)», «б)», «в)»
        под своей родительской строкой.
        """
        indicators: List[Dict] = []

        for row_idx in range(df.shape[0]):
            row = cls._blank_row_at(df, row_idx)
            if row is None:
                continue
            for entry in cls._values_at(df, row_idx):
                route_type, value = entry
                indicators.append({
                    'indicator_code': row.code,
                    'indicator_name': row.name,
                    'measure': row.measure,
                    'route_type': route_type,
                    'regularity': row.section,
                    'value': value,
                })

        return indicators

    @classmethod
    def _blank_row_at(cls, df: pd.DataFrame, row_idx: int) -> Optional[Ga12Row]:
        """Строка бланка, описанная в этой строке листа, либо None."""
        title = df.iloc[row_idx, TITLE_COL] if df.shape[1] > TITLE_COL else None
        if not cls._is_data_title(title):
            return None

        number = cls._blank_number(df.iloc[row_idx, ROW_NUMBER_COL]) if df.shape[1] > ROW_NUMBER_COL else None
        if number is not None:
            row = GA12_ROW_BY_BLANK_NUMBER.get(number)
            if row is None:
                return None
            cls._check_okei(df, row_idx, row)
            return row

        # Номера нет — это может быть строка детализации тоннокилометража.
        return cls._detail_row_at(df, row_idx, title)

    @classmethod
    def _detail_row_at(cls, df: pd.DataFrame, row_idx: int, title) -> Optional[Ga12Row]:
        marker = str(title).strip()[:2]
        row = GA12_DETAIL_ROW_BY_MARKER.get(marker)
        if row is None:
            return None
        cls._check_okei(df, row_idx, row)
        return row

    @classmethod
    def _check_okei(cls, df: pd.DataFrame, row_idx: int, row: Ga12Row) -> None:
        """Сверка с графой «Код по ОКЕИ»: пустая графа пропускается, чужая — отказ.

        Расхождение означает, что разбирается бланк с другой раскладкой строк, а
        не 12-ГА, который описан в utils/ga12_layout.py. Молча пропустить такую
        строку нельзя: отчёт уйдёт в базу неполным и без единого признака этого.
        """
        if df.shape[1] <= OKEI_COL:
            return
        raw = df.iloc[row_idx, OKEI_COL]
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return
        okei = str(raw).strip().split('.')[0]
        if okei and okei != row.okei:
            raise ValueError(
                f"Строка {row_idx + 1} листа: код по ОКЕИ «{okei}» не совпадает с бланком 12-ГА "
                f"(у строки «{row.name}» ожидается «{row.okei}»). Похоже, это другая форма "
                f"или изменённая раскладка бланка."
            )

    @classmethod
    def _values_at(cls, df: pd.DataFrame, row_idx: int) -> List[Tuple[str, Decimal]]:
        """Значения строки по видам сообщения.

        Графы бланка: 4 и 5 — международные (в базу идёт их сумма), 6 — внутренние
        всего, 7 — из них местные, 8 — из них субсидируемые. Графа 9 «ИТОГО
        гр.4+гр.5+гр.6» — производная, в базу не грузится.
        """
        out: List[Tuple[str, Decimal]] = []
        for route_type, cols in GA12_ROUTE_COLUMNS:
            total = Decimal('0')
            found = False
            for col in cols:
                if col >= df.shape[1]:
                    continue
                value = cls._safe_decimal(df.iloc[row_idx, col])
                if value is not None:
                    found = True
                    total += value
            if found:
                out.append((route_type, total))
        return out

    @staticmethod
    def _is_data_title(raw) -> bool:
        """Строка данных названа показателем; строка нумерации граф — нет.

        Под шапкой бланка идёт служебная строка «1|2|3|…|9», нумерующая графы. В её
        графе 2 стоит число 2, по которому она неотличима от строки 02 бланка, а в
        графах данных — номера 4…9, которые ушли бы в базу как значения.
        """
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return False
        text = str(raw).strip()
        if not text:
            return False
        return not text.replace(',', '.').replace('.', '').isdigit()

    @staticmethod
    def _blank_number(raw) -> Optional[int]:
        """№ строки из графы 2 бланка (1…20), иначе None."""
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or isinstance(raw, bool):
            return None
        try:
            number = int(str(raw).strip().replace(',', '.').split('.')[0])
        except (TypeError, ValueError):
            return None
        return number

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