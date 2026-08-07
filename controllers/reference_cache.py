# controllers/reference_cache.py
"""Кеш справочников, общий на всё приложение.

Списки предприятий и показателей кешировались в полях `FilterController`, а самих
контроллеров четыре: в главном окне и в каждом из двух виджетов фильтров. Кешей
получалось столько же, и сброс одного не касался остальных: после импорта отчёта
новой авиакомпании вкладка «Авиакомпании» продолжала показывать прежний список до
перезапуска программы (BUG-7, ARCH-7).

Кеш общий, потому что общий его источник — одна база на одного пользователя.
Инвалидация одна на всех: `reference_cache.clear()`.
"""
from typing import Any, Dict, List, Optional


class ReferenceDataCache:
    """Списки справочников: читаются один раз до явного сброса."""

    def __init__(self) -> None:
        self._entities: Dict[int, List[Any]] = {}
        self._indicators: Optional[List[Any]] = None

    def entities(self, mode: int) -> Optional[List[Any]]:
        return self._entities.get(mode)

    def put_entities(self, mode: int, rows: List[Any]) -> None:
        self._entities[mode] = rows

    def indicators(self) -> Optional[List[Any]]:
        return self._indicators

    def put_indicators(self, rows: List[Any]) -> None:
        self._indicators = rows

    def clear(self) -> None:
        self._entities.clear()
        self._indicators = None


# Экземпляр на приложение. Тесты и отдельные сценарии могут передать свой —
# `FilterController` принимает кеш параметром.
reference_cache = ReferenceDataCache()
