# utils/helpers.py
from decimal import Decimal
from typing import Any


def decimal_to_float(value: Any) -> Any:
    """Конвертирует Decimal в float для отображения"""
    if isinstance(value, Decimal):
        return float(value) if value else None
    return value


def format_number(value: Any, decimals: int = 2) -> str:
    """Форматирует число для отображения"""
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        return f"{float(value):,.{decimals}f}".replace(",", " ")
    return str(value)