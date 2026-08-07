# utils/constants.py
from db.models.enums import ShippingRegularity
from utils.ga12_layout import (
    GA12_CODES_BY_SECTION_KEY,
    GA12_CODES_FLAT,
    GA12_DETAIL_PARENT_BY_CODE,
    GA12_SECTION_HEADINGS,
    GA12_SECTION_ORDER,
)

MONTHS_RU = {
    'January': 'Январь', 'February': 'Февраль', 'March': 'Март',
    'April': 'Апрель', 'May': 'Май', 'June': 'Июнь',
    'July': 'Июль', 'August': 'Август', 'September': 'Сентябрь',
    'October': 'Октябрь', 'November': 'Ноябрь', 'December': 'Декабрь',
}
MONTHS_LIST = list(MONTHS_RU.keys())

ROUTE_TYPES_ORDER = ['trunk', 'local', 'interregional', 'subsidir']
ROUTE_TYPE_NAMES = {
    'trunk': 'Международные',
    'local': 'Внутренние',
    'interregional': 'Местные',
    'subsidir': 'Субсидируемые',
}

REGULARITY_ORDER = [
    'Регулярные коммерческие',
    'Не регулярные коммерческие',
    'Не коммерческие',
]

# Раскладка 12-ГА ниже целиком выведена из utils/ga12_layout.py — там описана
# каждая строка бланка. Прежде списки кодов были набраны здесь руками, а разделы
# нарезались из плоского списка срезами [:13], [13:22], [22:] (ARCH-12): правка
# любой строки требовала пересчитать границы, и они разошлись с самой формой.
GA12_CODE_ORDER_FLAT = list(GA12_CODES_FLAT)

# Ключи разделов на экране — значения ShippingRegularity: в этом виде раздел
# приходит из БД вместе с перевозкой.
_SECTION_LABEL = {key: ShippingRegularity[key].value for key in GA12_SECTION_ORDER}

GA12_REGULAR_CODES = list(GA12_CODES_BY_SECTION_KEY['regular'])
GA12_IRREGULAR_CODES = list(GA12_CODES_BY_SECTION_KEY['irregular'])
GA12_NONCOMMERCIAL_CODES = list(GA12_CODES_BY_SECTION_KEY['non_commercial'])

# Заголовки разделов на экране (как в типовом бланке)
GA12_SECTION_TITLE = {
    _SECTION_LABEL[key]: title for key, title in GA12_SECTION_HEADINGS.items()
}

GA12_CODES_BY_SECTION = {
    _SECTION_LABEL[key]: list(codes) for key, codes in GA12_CODES_BY_SECTION_KEY.items()
}

# Перед детализацией тонно-км (после строки 450) — как в бланке
GA12_SUBHEADING_VTOM = '      в том числе:'
GA12_DETAIL_TON_CODES = tuple(GA12_DETAIL_PARENT_BY_CODE)
# Строка детализации → её родитель. Бланк даёт детализацию только для регулярных
# перевозок, поэтому родитель у всех трёх один — 450. Связь проставляет импортёр.
GA12_DETAIL_TON_PARENT = dict(GA12_DETAIL_PARENT_BY_CODE)
# Родительские строки «Выполненный тоннокилометраж» (связь в indicators.parent_id)
GA12_TON_PARENT_CODES = frozenset(GA12_DETAIL_PARENT_BY_CODE.values())

MODE_AIRLINE = 1
MODE_AIRPORT = 2
VIEW_PIVOT = 'pivot'
VIEW_DETAIL = 'detail'

# Свод по одной АК: колонки по видам маршрута или одно значение на месяц (сумма по маршрутам).
PIVOT_LAYOUT_BY_ROUTES = "by_routes"
PIVOT_LAYOUT_SUMMARY = "summary"