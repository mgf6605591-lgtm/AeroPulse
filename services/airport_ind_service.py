# services/airport_ind_service.py
from typing import Dict, List
from controllers.AirportIndController import AirportIndController
from db.database import get_session
from db.models.entities import AirportIndicators


class AirportIndicatorService:

    @classmethod
    def get_all_indicators(cls) -> List[AirportIndicators]:
        with get_session() as session:
            return AirportIndController.get_all_indicators(session)

    @classmethod
    def filter_indicators(cls, filters: Dict) -> List[AirportIndicators]:
        with get_session() as session:
            return AirportIndController.filter_indicators(session, filters)