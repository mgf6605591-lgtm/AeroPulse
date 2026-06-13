from typing import Dict


class FilterValidateService:
    def __init__(self):
        pass

    @classmethod
    def validate_airline_indicator_filters(cls, filters: Dict[str, str]) -> bool:
        """Валидация фильтров для показателей авиакомпаний."""
        return True

    @classmethod
    def validate_airport_indicator_filters(cls, filters: Dict[str, str]) -> bool:
        """Валидация фильтров для показателей аэропортов."""
        return True
