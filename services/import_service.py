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

        # Форма определяется только по содержимому файла. Прежний откат на entity_type
        # сравнивал выбор пользователя сам с собой, поэтому расхождение не выявлялось
        # никогда — как раз для XLSX, который не возвращал data_type вовсе (DATA-6).
        parsed_type = data.get('data_type')
        if not parsed_type:
            return {
                'success': False,
                'message': 'Не удалось определить форму отчёта по содержимому файла. '
                           'Импорт отменён, чтобы данные не попали в чужую форму.',
                'source_file': os.path.basename(file_path),
            }
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

        # Отчётный период обязателен. Раньше парсер молча подставлял «январь 2025»,
        # и upsert по ключу (показатель, рейс, месяц, год) затирал настоящие январские
        # данные значениями чужого месяца — без резервной копии и следа в журнале (DATA-2).
        if not data.get('month') or not data.get('year'):
            return {
                'success': False,
                'period_required': True,
                'message': 'Не удалось определить отчётный период файла '
                           '(лист «Титул», ячейка D13).',
                'source_file': os.path.basename(file_path),
                'period_month': data.get('month'),
                'period_year': data.get('year'),
            }

        # Имя файла кладётся в разобранные данные, а не только в ответ: импортёр
        # записывает его в журнал вместе со счётчиками (FUNC-5).
        data['source_file'] = os.path.basename(file_path)

        # Импорт данных (предприятие уже существует в БД, не создаем новое)
        with get_session() as session:
            result = DataImporter.import_data(session, data)

        if isinstance(result, dict):
            result["source_file"] = os.path.basename(file_path)
            result["period_month"] = data.get("month")
            result["period_year"] = data.get("year")
            result["sheet_name"] = data.get("sheet_name")
        return result
    
    @classmethod
    def get_airlines(cls) -> list:
        """Действующие авиакомпании с ID.

        Выведенное из работы предприятие не предлагается для импорта: новые отчёты
        в него загружать незачем, а старые остаются доступны в сводах (SCH-10).
        """
        with get_session() as session:
            airlines = (
                session.query(Airline)
                .filter(Airline.is_active.is_(True))
                .order_by(Airline.name)
                .all()
            )
            return [(a.id, a.name.strip()) for a in airlines]

    @classmethod
    def get_airports(cls) -> list:
        """Действующие аэропорты с ID."""
        with get_session() as session:
            airports = (
                session.query(Airport)
                .filter(Airport.is_active.is_(True))
                .order_by(Airport.name)
                .all()
            )
            return [(a.id, a.name.strip()) for a in airports]