# services/import_service.py
import os

from importers.data_importer import DataImporter
from db.database import get_session
from services.parse_service import ParseService
from db.models.entities import Airline, Airport


class ImportService:
    """Сервис для импорта данных"""

    @classmethod
    def import_file(cls, file_path: str, entity_type: str = None, entity_id: int = None,
                    entity_name: str = None, month: str = None, year: int = None) -> dict:
        """
        Парсит файл и импортирует данные в БД.
        
        Args:
            file_path: путь к файлу
            entity_type: тип предприятия ('airline' или 'airport')
            entity_id: ID предприятия
            entity_name: название предприятия (если ID не указан)
            month: месяц (если не удалось определить из файла)
            year: год (если не удалось определить из файла)
            
        Returns:
            dict: результат импорта
        """
        # Проверка существования предприятия по ID
        if entity_id:
            with get_session() as session:
                if entity_type == 'airline':
                    entity = session.get(Airline, entity_id)
                else:
                    entity = session.get(Airport, entity_id)
                
                if not entity:
                    return {
                        'success': False,
                        'message': f'Предприятие с ID {entity_id} не найдено в базе данных.'
                    }
                entity_name = entity.name.strip()
        elif entity_name:
            # Поиск по названию (резервный вариант)
            with get_session() as session:
                if entity_type == 'airline':
                    entity = session.query(Airline).filter(Airline.name == entity_name).first()
                else:
                    entity = session.query(Airport).filter(Airport.name == entity_name).first()
                
                if not entity:
                    return {
                        'success': False,
                        'message': f'Предприятие "{entity_name}" не найдено в базе данных.'
                    }
                entity_id = entity.id
        else:
            return {
                'success': False,
                'message': 'Не указано предприятие для импорта данных.'
            }

        # Парсинг файла с передачей информации о предприятии
        try:
            data = ParseService.parse_file(
                file_path,
                month=month,
                year=year,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
            )
        except ValueError as e:
            return {
                'success': False,
                'message': str(e),
                'source_file': os.path.basename(file_path),
            }

        parsed_type = data.get('data_type') or data.get('entity_type')
        if entity_type == 'airport' and parsed_type == 'airline':
            return {
                'success': False,
                'message': 'Выбран аэропорт, а файл относится к форме 12-ГА (авиакомпании). Для 15-ГА нужен XML с колонками 3–13 и строками 10–90.',
                'source_file': os.path.basename(file_path),
            }
        if entity_type == 'airline' and parsed_type == 'airport':
            return {
                'success': False,
                'message': 'Выбрана авиакомпания, а файл относится к форме 15-ГА (аэропорты). Выберите тип «Аэропорт».',
                'source_file': os.path.basename(file_path),
            }

        # Импорт данных (предприятие уже существует в БД, не создаем новое)
        with get_session() as session:
            result = DataImporter.import_data(session, data)
        
        if isinstance(result, dict):
            result["source_file"] = os.path.basename(file_path)
            result["period_month"] = data.get("month")
            result["period_year"] = data.get("year")
        return result
    
    @classmethod
    def get_airlines(cls) -> list:
        """Возвращает список всех авиакомпаний с ID"""
        with get_session() as session:
            airlines = session.query(Airline).order_by(Airline.name).all()
            return [(a.id, a.name.strip()) for a in airlines]
    
    @classmethod
    def get_airports(cls) -> list:
        """Возвращает список всех аэропортов с ID"""
        with get_session() as session:
            airports = session.query(Airport).order_by(Airport.name).all()
            return [(a.id, a.name.strip()) for a in airports]