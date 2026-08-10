# parsers/f15_fkp_xlsx_parser.py
"""Импорт XLSX формы 15-ГА, сданной одним бланком за всё предприятие.

ФКП «Аэропорты Севера» присылает не отдельный бланк на аэропорт, а одну книгу:
сводный блок предприятия, а под ним по блоку на каждый из его аэропортов. Блок
опознаётся подписью «Название аэропорта», строки внутри — «1. Внутренние
регулярные-всего», «2. Внутренние нерегулярные - всего» и «ВСЕГО».

Раскладка граф своя, не как в типовом бланке 15-ГА: между графами пассажиров
вставлены «в т.ч. РБ», поэтому графа 5 этого бланка — это графа 5 типового, а
графа 11 — уже графа 8. Соответствие задано таблицей `FKP_GRAPH_TO_F15_GRAPH`, а
коды, названия и единицы измерения показателей берутся оттуда же, откуда их
берёт разбор XML: один и тот же отчёт обязан лечь в базу одинаково, каким бы
путём он ни пришёл.

Международных строк в этом бланке нет вовсе — предприятие возит только внутри
страны, — поэтому «ВСЕГО» записывается сразу двумя строками типового бланка:
07 «Внутренние - всего» и 08 «Коммерческие перевозки - всего». Они равны, пока
международных перевозок нет; строка 08 нужна своду, который читает именно её.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from parsers.base_parser import BaseParser
from parsers.f15_xml_parser import (
    F15_COL_TITLES,
    F15_COL_TO_METRIC,
    F15_ROW_TITLES,
    F15_XML_ROW_TO_RC,
    F15XMLParser,
)
from parsers.xlsx_common import find_sheet, sheet_names

# Подпись, с которой начинается блок: у предприятия название дописано в той же
# ячейке через подчёркивания, у аэропорта — в ячейке правее.
BLOCK_MARKER = "название аэропорта"

# Меньше двух блоков — это обычный бланк 15-ГА на один аэропорт, его разбирает
# `f15_xlsx_parser`. Сводный бланк предприятия начинается с блока самого
# предприятия, поэтому даже у предприятия с единственным аэропортом блоков два.
MIN_BLOCKS = 2

# Строка блока → код строки типового бланка. «ВСЕГО» даёт сразу две: см. модуль.
ROW_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1. внутренние регулярные-всего", ("R05",)),
    ("2. внутренние нерегулярные - всего", ("R06",)),
    ("всего", ("R07", "R08")),
)

# Графа этого бланка → графа типового 15-ГА (ключи `F15_COL_TO_METRIC`).
FKP_GRAPH_TO_F15_GRAPH: dict[int, str] = {
    2: "3",    # количество отбывших-прибывших ВС
    3: "4",    # пассажиры отправленные
    5: "5",    # пассажиры принятые
    7: "6",    # пассажиры всего
    9: "7",    # пассажиры, прямой транзит
    11: "8",   # груз отгружено
    12: "9",   # груз разгружено
    13: "10",  # груз всего
    14: "11",  # почта отгружено
    15: "12",  # почта разгружено
    16: "13",  # почта всего
}

# Код строки типового бланка → его номер в XML-выгрузке: оттуда берётся название.
RC_TO_XML_ROW: dict[str, int] = {rc: code for code, rc in F15_XML_ROW_TO_RC.items()}

# Вид перевозок стоит в первой графе, как и в типовом бланке.
ROW_LABEL_COL = 0


def _text(raw) -> str:
    """Содержимое ячейки одной строкой без повторяющихся пробелов."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    return re.sub(r"\s+", " ", str(raw)).strip()


def _key(raw) -> str:
    """Текст ячейки в виде, пригодном для сравнения с подписью бланка."""
    return _text(raw).lower().replace("ё", "е")


class Block:
    """Блок бланка: предприятие или один его аэропорт."""

    __slots__ = ("name", "first_row", "last_row")

    def __init__(self, name: str, first_row: int, last_row: int):
        self.name = name
        self.first_row = first_row
        self.last_row = last_row


class F15FKPXLSXParser(BaseParser):
    """Парсер сводного бланка 15-ГА → отчётность каждого аэропорта предприятия."""

    @classmethod
    def parse_file(cls, file_name: str, month: str | None = None, year: int | None = None,
                   entity_type: str | None = None, entity_id: int | None = None,
                   entity_name: str | None = None) -> dict[str, Any]:
        df, sheet_name = cls._read_sheet(file_name)
        blocks = cls._blocks(df)

        # Период: явные параметры вызова важнее того, что написано на листе.
        # Заглушек нет — неопределённый период уходит наверх как None (DATA-2).
        cell_month, cell_year = cls._period_from_df(df)
        month = month or cell_month
        year = year if year is not None else cell_year

        # Предприятие — первый блок бланка, остальные входят в него. Выбор в
        # диалоге импорта здесь ни при чём: в файле предприятий столько, сколько
        # блоков, и подставить вместо них одно выбранное значило бы свалить
        # отчётность тридцати аэропортов в один.
        enterprise = blocks[0].name
        airports = [
            {
                "name": block.name,
                "parent_name": None if index == 0 else enterprise,
                "indicators": cls._extract_indicators(df, block),
            }
            for index, block in enumerate(blocks)
        ]

        return {
            "data_type": "airport",
            "entity_type": entity_type or "airport",
            "entity_id": entity_id,
            "sheet_name": sheet_name,
            "airports": airports,
            "month": month,
            "year": year,
        }

    @classmethod
    def is_fkp_workbook(cls, file_name: str) -> bool:
        """Есть ли в книге сводный бланк предприятия. Используется для выбора парсера."""
        df, _ = find_sheet(file_name, cls._looks_like_fkp)
        return df is not None

    @classmethod
    def _looks_like_fkp(cls, df: pd.DataFrame) -> bool:
        """Лист опознаётся по блокам, а не по набору слов.

        Отдельная подпись «Название аэропорта» есть и в типовом бланке на один
        аэропорт: сводным лист делает то, что таких блоков несколько и в каждом
        стоят строки формы.
        """
        blocks = cls._blocks(df)
        if len(blocks) < MIN_BLOCKS:
            return False
        return all(cls._row_codes(df, block) for block in blocks)

    @classmethod
    def _read_sheet(cls, file_name: str) -> tuple[pd.DataFrame, str]:
        df, name = find_sheet(file_name, cls._looks_like_fkp)
        if df is None:
            raise ValueError(
                "Не удалось распознать сводный бланк 15-ГА: ни на одном листе книги "
                f"({', '.join(sheet_names(file_name))}) нет блоков «Название аэропорта» "
                "со строками формы."
            )
        return df, name

    @classmethod
    def _blocks(cls, df: pd.DataFrame) -> list[Block]:
        """Блоки листа: подпись «Название аэропорта» открывает блок, следующая — закрывает."""
        starts: list[tuple[int, str]] = []
        for r in range(df.shape[0]):
            for c in range(df.shape[1]):
                if not _key(df.iloc[r, c]).startswith(BLOCK_MARKER):
                    continue
                name = cls._block_name(df, r, c)
                if name:
                    starts.append((r, name))
                break

        blocks: list[Block] = []
        for index, (row, name) in enumerate(starts):
            last = starts[index + 1][0] - 1 if index + 1 < len(starts) else df.shape[0] - 1
            blocks.append(Block(name, row, last))
        return blocks

    @staticmethod
    def _block_name(df: pd.DataFrame, row: int, col: int) -> str:
        """Название из подписи блока.

        У предприятия оно дописано в той же ячейке и подчёркнуто до края поля
        («Название аэропорта ____ФКП "Аэропорты Севера"____»), у аэропорта стоит
        в ячейке правее. Разбираются оба случая: колонку названия в бланке
        занимать необязательно, а подчёркивания — оформление поля, а не имя.
        """
        inline = _text(df.iloc[row, col])
        tail = inline[len(BLOCK_MARKER):] if len(inline) > len(BLOCK_MARKER) else ""
        tail = tail.strip("_ :").strip()
        if tail:
            return tail

        for c in range(col + 1, df.shape[1]):
            candidate = _text(df.iloc[row, c]).strip("_ :").strip()
            if candidate:
                # Дальше по строке идут подписи периодов правой колонки бланка —
                # названием аэропорта они не являются.
                return "" if candidate.lower().startswith("за ") else candidate
        return ""

    @classmethod
    def _row_codes(cls, df: pd.DataFrame, block: Block) -> dict[int, tuple[str, ...]]:
        """Строки блока: номер строки листа → коды строк типового бланка."""
        found: dict[int, tuple[str, ...]] = {}
        if df.shape[1] <= ROW_LABEL_COL:
            return found
        for r in range(block.first_row, min(block.last_row, df.shape[0] - 1) + 1):
            label = _key(df.iloc[r, ROW_LABEL_COL])
            for marker, codes in ROW_LABELS:
                if label == marker:
                    found[r] = codes
                    break
        return found

    @classmethod
    def _extract_indicators(cls, df: pd.DataFrame, block: Block) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r, codes in sorted(cls._row_codes(df, block).items()):
            for rc in codes:
                out.extend(cls._row_indicators(df, r, rc))
        return out

    @classmethod
    def _row_indicators(cls, df: pd.DataFrame, row: int, rc: str) -> list[dict[str, Any]]:
        row_title = F15_ROW_TITLES.get(RC_TO_XML_ROW.get(rc, -1), rc)
        out: list[dict[str, Any]] = []
        for graph, std_graph in FKP_GRAPH_TO_F15_GRAPH.items():
            col = graph - 1
            if col >= df.shape[1]:
                continue
            value = F15XMLParser._parse_cell_value(_text(df.iloc[row, col]))
            if value is None:
                continue
            out.append(
                {
                    "indicator_code": f"15ГА-{rc}-{F15_COL_TO_METRIC[std_graph]}",
                    "indicator_name": f"{row_title} — {F15_COL_TITLES[std_graph]}",
                    "measure": F15XMLParser._measure_for_col(std_graph),
                    "value": value,
                }
            )
        return out

    @classmethod
    def _period_from_df(cls, df: pd.DataFrame) -> tuple[str | None, int | None]:
        """Отчётный период — первая подпись «за __месяц_год__г.» в графе видов перевозок.

        Читается с того же листа, где лежат цифры, и той же разборкой, что у
        12-ГА: формулировка бланка одна и та же (DATA-3). Правее по листу идёт
        колонка со списком всех периодов года — образец для других месяцев, а не
        период этого файла, — поэтому просматривается только первая графа.
        """
        from parsers.xlsx_parser import XLSXParser

        if df.shape[1] <= ROW_LABEL_COL:
            return None, None
        for r in range(df.shape[0]):
            month, year = XLSXParser._parse_month_year_value(df.iloc[r, ROW_LABEL_COL])
            if month and year:
                return month, year
        return None, None
