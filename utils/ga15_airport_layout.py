# utils/ga15_airport_layout.py
"""
Форма 15-ГА (аэропорт): структура строк и колонок как в типовом Excel «15-ГА».

Ячейки данных заполняются из показателей БД с кодами вида:
  15ГА-{ключ строки}-{метка метрики}
например: 15ГА-R01-ВС, 15ГА-R05-ПАС_ОТП.

Если импорт записывает другие коды — добавьте их в GA15_CODE_ALIASES в data_controller.
"""

from typing import List, Tuple, Optional, Any

# Ключи метрик (суффикс кода показателя после второго дефиса)
GA15_METRIC_TAGS = (
    "ВС",
    "ПАС_ОТП",
    "ПАС_ПРИН",
    "ПАС_ВСЕГО",
    "ПАС_ТРАНЗ",
    "ГР_ОТГР",
    "ГР_РАЗГ",
    "ГР_ВСЕГО",
    "ПЧ_ОТГР",
    "ПЧ_РАЗГ",
    "ПЧ_ВСЕГО",
)

# Нижний ряд заголовков (под группами)
GA15_FLAT_HEADERS: List[str] = [
    "Виды перевозок",
    "№ строки",
    "ВС, ед.",
    "Отправленных",
    "Принятых",
    "Всего\n(гр.4+гр.5)",
    "Прямой транзит",
    "Отгружено",
    "Разгружено",
    "Всего\n(гр.8+гр.9)",
    "Отгружено",
    "Разгружено",
    "Всего\n(гр.11+гр.12)",
]

# Группы верхнего уровня для MultiLevelHeaderView: (first_col, last_col, label)
GA15_HEADER_GROUPS: List[Tuple[int, int, str]] = [
    (2, 2, "Количество отбывших-прибывших ВС - всего, ед."),
    (3, 6, "Пассажиры, чел."),
    (7, 9, "Груз, т"),
    (10, 12, "Почта, т"),
]

# Ключи колонок данных в pivot-словаре (13 столбцов)
GA15_KEYS: List[str] = [f"ga15_{i}" for i in range(13)]


# В бланке 15-ГА в неприменимых графах напечатана «Х» — кириллическая, как в
# самой форме. Это значит «показатель здесь не заполняется», а не «данных нет»:
# отсутствие данных в заполняемой графе — это ноль (BUG-30).
GA15_NOT_FILLED = "Х"


class Ga15RowSpec:
    __slots__ = ("kind", "title", "line_display", "row_code", "not_filled")

    def __init__(
        self,
        kind: str,
        title: str,
        line_display: Optional[Any] = None,
        row_code: Optional[str] = None,
        not_filled: Tuple[str, ...] = (),
    ):
        """
        kind: section | subheading | subdetail | data | filler | footer
        row_code: суффикс для кодов показателей 15ГА-{row_code}-{METRIC}; None — строка без числовых данных
        not_filled: метки метрик, у которых в бланке напечатана «Х»
        """
        self.kind = kind
        self.title = title
        self.line_display = line_display
        self.row_code = row_code
        self.not_filled = frozenset(not_filled)


# Строки листа «15-ГА» (без служебных блоков подписей внизу)
GA15_TABLE_ROWS: List[Ga15RowSpec] = [
    Ga15RowSpec("title", 'Наименование аэропорта: {airport_name}', None, None),
    Ga15RowSpec("spacer", "", None, None),
    Ga15RowSpec("spacer", "", None, None),
    Ga15RowSpec("period", "за {period_label}", None, None),
    Ga15RowSpec("section", "Коммерческие перевозки", None, None),
    Ga15RowSpec("data", "Международные регулярные", 1, "R01"),
    Ga15RowSpec("data", "Международные нерегулярные", 2, "R02"),
    Ga15RowSpec("data", "Международные - всего (стр. 01+стр. 02)", 3, "R03"),
    Ga15RowSpec("subheading", "в том числе:", 4, None),
    Ga15RowSpec("subdetail", "иностранными авиакомпаниями", None, "R04ИНО"),
    Ga15RowSpec("data", "Внутренние регулярные", 5, "R05"),
    Ga15RowSpec("data", "Внутренние нерегулярные", 6, "R06"),
    Ga15RowSpec("data", "Внутренние - всего (стр. 05 + стр. 06)", 7, "R07"),
    Ga15RowSpec(
        "data",
        "Коммерческие перевозки - всего (стр. 03 + стр. 07)",
        8,
        "R08",
    ),
    # Строка 09: в бланке заполняется только количество ВС, в графах 4…13 стоит
    # «Х». Перечень взят из настоящей формы, а не выведен из общего правила:
    # прежде «Х» подставлялась во все одиннадцать граф, включая количество ВС,
    # где должно стоять число (BUG-30).
    Ga15RowSpec(
        "data",
        "Все прочие операции",
        9,
        "R09",
        not_filled=tuple(tag for tag in GA15_METRIC_TAGS if tag != "ВС"),
    ),
]
