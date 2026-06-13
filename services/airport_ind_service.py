# services/airport_ind_service.py
from typing import Dict, List, Optional
from controllers.AirportIndController import AirportIndController
from db.database import get_session
from db.models.entities import AirportIndicators


class AirportIndicatorService:

    @classmethod
    def get_all_indicators(cls) -> List[AirportIndicators]:
        with get_session() as session:
            return AirportIndController.get_all_indicators(session)

    @classmethod
    def get_indicator_by_id(cls, indicator_id: int) -> Optional[AirportIndicators]:
        with get_session() as session:
            return AirportIndController.get_indicator_by_id(session, indicator_id)

    @classmethod
    def filter_indicators(cls, filters: Dict) -> List[AirportIndicators]:
        with get_session() as session:
            return AirportIndController.filter_indicators(session, filters)