from enum import Enum


class RouteType(Enum):
    trunk = "Международные"
    local = "Внутренние"
    interregional = "Местные"
    subsidir = "Субсидируемые"


class ShippingRegularity(Enum):
    regular = "Регулярные коммерческие"
    irregular = "Не регулярные коммерческие"
    non_commercial = "Не коммерческие"


class UserPosition(Enum):
    admin = "Администратор"
    guest = "Гость"
    employee = "Сотрудник"


class Months(Enum):
    January = "Январь"
    February = "Февраль"
    March = "Март"
    April = "Апрель"
    May = "Май"
    June = "Июнь"
    July = "Июль"
    August = "Август"
    September = "Сентябрь"
    October = "Октябрь"
    November = "Ноябрь"
    December = "Декабрь"
