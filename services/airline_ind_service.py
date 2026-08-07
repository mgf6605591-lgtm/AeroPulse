# services/airline_ind_service.py
from typing import Dict, List
from controllers.AirlineIndController import AirlineIndController
from db.database import get_session
from db.models.entities import AirlineIndicators


class AirlineIndicatorService:

    @classmethod
    def get_all_indicators(cls) -> List[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.get_all_indicators(session)

    @classmethod
    def filter_indicators(cls, filters: Dict) -> List[AirlineIndicators]:
        with get_session() as session:
            return AirlineIndController.filter_indicators(session, filters)