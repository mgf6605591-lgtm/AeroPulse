# forms/widgets/period_guard.py
"""Проверка порядка границ периода перед перестроением отчёта (BUG-16).

Границы брались из комбобоксов как есть. Выбрав «с декабря 2025 по январь 2024»,
пользователь получал пустой отчёт: условие отбора «начало ≤ ключ ≤ конец» не
выполняется ни для одной записи — и ни одного объяснения, почему таблица пуста.

Границы **не переставляются местами молча**. Перестановка выглядит услугой, но
превращает заведомо ошибочный ввод в отчёт за двадцать четыре месяца, которого
никто не просил, — а разошедшийся с экраном период читается как правда. В этом
проекте принято отказывать, а не угадывать: то же правило перекрыло ворота
импорта (DATA-2, DATA-4).

Модуль общий на обе вкладки: и фильтры авиакомпаний, и фильтры аэропортов
применяют период одной и той же кнопкой.
"""
from PyQt6.QtWidgets import QMessageBox

from controllers.filter_controller import period_from_widget, period_is_inverted
from utils.constants import MONTHS_LIST, MONTHS_RU

TITLE = "Период задан наоборот"


def period_label(bound) -> str:
    """«Декабрь 2025» из пары (год, номер месяца)."""
    year, month = bound
    return f"{MONTHS_RU[MONTHS_LIST[month - 1]]} {year}"


def period_is_usable(widget, parent=None) -> bool:
    """True — период годен и отчёт можно перестраивать.

    False — границы перевёрнуты; пользователю показано, что именно не так, а
    отчёт остаётся прежним. Комбобоксы не трогаются: их выставил человек, и
    поправить их — тоже его дело.
    """
    bounds = period_from_widget(widget)
    if not period_is_inverted(bounds):
        return True

    start, end = bounds
    QMessageBox.warning(
        parent or widget,
        TITLE,
        f"Начало периода — {period_label(start)} — позже его конца, "
        f"{period_label(end)}.\n\n"
        "Отчёт оставлен прежним. Поменяйте границы местами и примените снова.",
    )
    return False
