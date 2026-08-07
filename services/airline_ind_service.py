# services/airline_ind_service.py
from typing import Any, Dict, List
from controllers.AirlineIndController import AirlineIndController
from db.database import get_session
from db.models.entities import AirlineIndicators


class AirlineIndicatorService:

    @classmethod
    def get_all_indicators(cls) -> List[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.get_all_indicators(session)

    @classmethod
    def aggregate(cls, filters: Dict) -> List[Any]:
        """Ячейки свода: суммы по группам вместо самих фактов (PERF-2)."""
        with get_session() as session:
            return AirlineIndController.aggregate(session, filters or {})

    @classmethod
    def filter_indicators(cls, filters: Dict) -> List[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.filter_indicators(session, filters)