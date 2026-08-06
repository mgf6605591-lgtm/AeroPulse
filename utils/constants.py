# utils/constants.py
from db.models.enums import RouteType

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

# Порядок показателей как в типовом Excel 12-ГА (сверху вниз: регулярные → нерегулярные → некоммерческие).
# Доп. коды 450пас/450гр/450пч — из XML-метаформы (детализация тонно-км).
GA12_CODE_ORDER_FLAT = [
    '965', '642', '356', '792', '168', '168п', '423', '423п', '450',
    '450пас', '450гр', '450пч',
    '450п',
    '965н', '642н', '356н', '792н', '168н', '423н', '423нп', '450н', '450нп',
    '965нк', '642нк', '356нк', '792нк', '168нк', '423нк', '423нкп', '450нк', '450нкп',
]

# Три блока бланка 12-ГА (как в Excel / приложении к форме)
GA12_REGULAR_CODES = GA12_CODE_ORDER_FLAT[:13]
GA12_IRREGULAR_CODES = GA12_CODE_ORDER_FLAT[13:22]
GA12_NONCOMMERCIAL_CODES = GA12_CODE_ORDER_FLAT[22:]

# Заголовки разделов на экране (как в типовом бланке)
GA12_SECTION_TITLE = {
    'Регулярные коммерческие': 'РЕГУЛЯРНЫЕ КОММЕРЧЕСКИЕ ПЕРЕВОЗКИ',
    'Не регулярные коммерческие': 'НЕРЕГУЛЯРНЫЕ КОММЕРЧЕСКИЕ ПЕРЕВОЗКИ',
    'Не коммерческие': 'НЕКОММЕРЧЕСКИЕ ПОЛЕТЫ',
}

GA12_CODES_BY_SECTION = {
    'Регулярные коммерческие': GA12_REGULAR_CODES,
    'Не регулярные коммерческие': GA12_IRREGULAR_CODES,
    'Не коммерческие': GA12_NONCOMMERCIAL_CODES,
}

# Перед детализацией тонно-км (после строки 450) — как в бланке
GA12_SUBHEADING_VTOM = '      в том числе:'
GA12_DETAIL_TON_CODES = ('450пас', '450гр', '450пч')
# Родительские строки «Выполненный тоннокилометраж» по разделам бланка (связь в indicators.parent_id)
GA12_TON_PARENT_CODES = frozenset({'450', '450н', '450нк'})
# Строка детализации → её родитель. Бланк даёт детализацию только для регулярных перевозок,
# поэтому родитель у всех трёх один — 450. Связь проставляет импортёр.
GA12_DETAIL_TON_PARENT = {code: '450' for code in GA12_DETAIL_TON_CODES}

MODE_AIRLINE = 1
MODE_AIRPORT = 2
VIEW_PIVOT = 'pivot'
VIEW_DETAIL = 'detail'

# Свод по одной АК: колонки по видам маршрута или одно значение на месяц (сумма по маршрутам).
PIVOT_LAYOUT_BY_ROUTES = "by_routes"
PIVOT_LAYOUT_SUMMARY = "summary"