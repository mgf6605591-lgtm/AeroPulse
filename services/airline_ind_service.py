# services/airline_ind_service.py
from typing import Dict, List, Optional
from controllers.AirlineIndController import AirlineIndController
from db.database import get_session
from db.models.entities import AirlineIndicators


class AirlineIndicatorService:

    @classmethod
    def get_all_indicators(cls) -> List[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.get_all_indicators(session)

    @classmethod
    def get_indicator_by_id(cls, indicator_id: int) -> Optional[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.get_indicator_by_id(session, indicator_id)

    @classmethod
    def filter_indicators(cls, filters: Dict) -> List[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.filter_indicators(session, filters)