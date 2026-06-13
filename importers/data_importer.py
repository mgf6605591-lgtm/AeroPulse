# importers/data_importer.py
from decimal import Decimal
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.orm import sessionmaker
from db.database import get_session, engine
from db.models.entities import (
    Airline, Airport, Indicator, Shipping, Route, 
    AirlineIndicators, AirportIndicators, Locality
)
from db.models.enums import ShippingRegularity, RouteType, Months
import time


class DataImporter:
    """Импортер данных в БД с обработкой блокировок"""

    @classmethod
    def _route_import(cls, session, data: dict) -> dict:
        """Маршрутизация: сначала явный data_type, иначе по составу payload (без ложного срабатывания на 15-ГА)."""
        dt = data.get("data_type") or data.get("entity_type")
        if dt == "airport":
            return cls._import_airport_data(session, data)
        if dt == "airline":
            return cls._import_airline_data(session, data)
        if "airline" in data:
            return cls._import_airline_data(session, data)
        if "airport" in data:
            return cls._import_airport_data(session, data)
        return {
            "success": False,
            "message": f"Неизвестный тип данных: {dt}",
        }

    @classmethod
    def import_data(cls, session, data: dict) -> dict:
        """Основной метод импорта данных"""
        try:
            return cls._route_import(session, data)

        except OperationalError as e:
            if "database is locked" in str(e):
                return cls._retry_import(data, max_retries=3)
            raise
    
    @classmethod
    def _retry_import(cls, data: dict, max_retries: int = 3) -> dict:
        """Повторяет импорт при блокировке базы данных"""
        for attempt in range(max_retries):
            try:
                time.sleep(0.5 * (attempt + 1))
                with get_session() as session:
                    return cls._route_import(session, data)
            except OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    continue
                return {
                    'success': False,
                    'message': f'Ошибка импорта после {max_retries} попыток: {str(e)}'
                }
            except Exception as e:
                return {
                    'success': False,
                    'message': f'Ошибка при импорте: {str(e)}'
                }
        return {'success': False, 'message': 'Не удалось выполнить импорт'}

    @classmethod
    def _import_airline_data(cls, session, data: dict) -> dict:
        """Импорт данных для авиакомпаний"""
        try:
            # Получаем или создаем индикаторы
            indicators_map = {}
            for indicator_data in data.get('indicators', []):
                code = indicator_data.get('indicator_code') or indicator_data.get('code')
                name = indicator_data.get('indicator_name') or indicator_data.get('name')
                measure = indicator_data.get('measure', '')
                
                if not code and not name:
                    continue
                
                indicator = None
                if code:
                    indicator = session.query(Indicator).filter(
                        Indicator.code == code
                    ).first()
                
                if not indicator and name:
                    indicator = session.query(Indicator).filter(
                        Indicator.name == name
                    ).first()
                
                if not indicator:
                    indicator = Indicator(
                        code=code or name[:10] if name else 'UNK',
                        name=name or code,
                        measure=measure,
                    )
                    session.add(indicator)
                    session.flush()
                
                indicators_map[(code, name)] = indicator
            
            # Получаем авиакомпанию
            airline_data = data.get('airline', {})
            airline_id = data.get('entity_id') or airline_data.get('id')
            
            if airline_id:
                airline = session.query(Airline).filter(Airline.id == airline_id).first()
                if not airline:
                    return {
                        'success': False,
                        'message': f'Авиакомпания с ID {airline_id} не найдена'
                    }
            else:
                airline_name = airline_data.get('name', '')
                airline = session.query(Airline).filter(
                    Airline.name == airline_name
                ).first()
                
                if not airline:
                    return {
                        'success': False,
                        'message': f'Авиакомпания "{airline_name}" не найдена в базе данных. Пожалуйста, выберите существующую авиакомпанию.'
                    }
            
            # Получаем месяц и год
            month_name = data.get('month', 'January')
            year = data.get('year', 2025)
            
            month_enum = None
            for m in Months:
                if m.name == month_name:
                    month_enum = m
                    break
            if not month_enum:
                month_enum = Months.January
            
            total_imported = 0
            total_updated = 0
            
            for indicator_data in data.get('indicators', []):
                code = indicator_data.get('indicator_code') or indicator_data.get('code')
                name = indicator_data.get('indicator_name') or indicator_data.get('name')
                
                indicator = indicators_map.get((code, name))
                if not indicator:
                    continue
                
                # Получаем или создаем маршрут (Shipping)
                route_type_str = indicator_data.get('route_type', 'local')
                regularity_str = indicator_data.get('regularity', 'regular')
                
                # Преобразуем в enum
                route_type = None
                for rt in RouteType:
                    if rt.name == route_type_str or rt.value == route_type_str:
                        route_type = rt
                        break
                if not route_type:
                    route_type = RouteType.local
                
                regularity = None
                for reg in ShippingRegularity:
                    if reg.name == regularity_str or reg.value == regularity_str:
                        regularity = reg
                        break
                if not regularity:
                    regularity = ShippingRegularity.regular
                
                # Ищем существующий маршрут (Shipping)
                # Используем связь с таблицей Route через route_id
                # Сначала ищем или создаем Route
                route = session.query(Route).filter(
                    Route.type == route_type,
                    Route.regularity == regularity
                ).first()
                
                if not route:
                    route = Route(
                        type=route_type,
                        regularity=regularity
                    )
                    session.add(route)
                    session.flush()
                
                # Ищем Shipping по airline_id и route_id
                shipping = session.query(Shipping).filter(
                    Shipping.airline_id == airline.id,
                    Shipping.route_id == route.id
                ).first()
                
                if not shipping:
                    shipping = Shipping(
                        airline_id=airline.id,
                        route_id=route.id
                    )
                    session.add(shipping)
                    session.flush()
                
                # Получаем значение
                value = indicator_data.get('value')
                if value is None:
                    continue
                
                if isinstance(value, Decimal):
                    value = float(value)
                
                # Проверяем существующую запись
                existing = session.query(AirlineIndicators).filter(
                    AirlineIndicators.indicator_id == indicator.id,
                    AirlineIndicators.shipping_id == shipping.id,
                    AirlineIndicators.month == month_enum,
                    AirlineIndicators.year == year
                ).first()
                
                if existing:
                    existing.value = value
                    total_updated += 1
                else:
                    airline_ind = AirlineIndicators(
                        indicator_id=indicator.id,
                        shipping_id=shipping.id,
                        month=month_enum,
                        year=year,
                        value=value
                    )
                    session.add(airline_ind)
                    total_imported += 1
                
                # Периодически сбрасываем транзакцию для предотвращения блокировок
                if (total_imported + total_updated) % 50 == 0:
                    session.flush()
            
            session.commit()
            
            return {
                'success': True,
                'message': f'Импорт завершен. Добавлено: {total_imported}, Обновлено: {total_updated}',
                'imported': total_imported,
                'updated': total_updated
            }
            
        except IntegrityError as e:
            session.rollback()
            return {
                'success': False,
                'message': f'Ошибка целостности данных: {str(e)}'
            }
        except OperationalError as e:
            session.rollback()
            if "database is locked" in str(e):
                raise
            return {
                'success': False,
                'message': f'Ошибка базы данных: {str(e)}'
            }
        except Exception as e:
            session.rollback()
            return {
                'success': False,
                'message': f'Неожиданная ошибка: {str(e)}'
            }

    @classmethod
    def _import_airport_data(cls, session, data: dict) -> dict:
        """Импорт данных для аэропортов"""
        try:
            indicators_map = {}
            for indicator_data in data.get('indicators', []):
                code = indicator_data.get('indicator_code') or indicator_data.get('code')
                name = indicator_data.get('indicator_name') or indicator_data.get('name')
                measure = indicator_data.get('measure', '')
                
                if not code and not name:
                    continue
                
                indicator = None
                if code:
                    indicator = session.query(Indicator).filter(
                        Indicator.code == code
                    ).first()
                
                if not indicator and name:
                    indicator = session.query(Indicator).filter(
                        Indicator.name == name
                    ).first()
                
                if not indicator:
                    indicator = Indicator(
                        code=code or name[:10] if name else 'UNK',
                        name=name or code,
                        measure=measure,
                    )
                    session.add(indicator)
                    session.flush()
                
                indicators_map[(code, name)] = indicator
            
            # Получаем аэропорт
            airport_data = data.get('airport', {})
            airport_id = data.get('entity_id') or airport_data.get('id')
            
            if airport_id:
                airport = session.query(Airport).filter(Airport.id == airport_id).first()
                if not airport:
                    return {
                        'success': False,
                        'message': f'Аэропорт с ID {airport_id} не найден'
                    }
            else:
                airport_name = airport_data.get('name', '')
                airport = session.query(Airport).filter(
                    Airport.name == airport_name
                ).first()
                
                if not airport:
                    return {
                        'success': False,
                        'message': f'Аэропорт "{airport_name}" не найден в базе данных. Пожалуйста, выберите существующий аэропорт.'
                    }
            
            month_name = data.get('month', 'January')
            year = data.get('year', 2025)
            
            month_enum = None
            for m in Months:
                if m.name == month_name:
                    month_enum = m
                    break
            if not month_enum:
                month_enum = Months.January
            
            total_imported = 0
            total_updated = 0
            
            for indicator_data in data.get('indicators', []):
                code = indicator_data.get('indicator_code') or indicator_data.get('code')
                name = indicator_data.get('indicator_name') or indicator_data.get('name')
                
                indicator = indicators_map.get((code, name))
                if not indicator:
                    continue
                
                value = indicator_data.get('value')
                if value is None:
                    continue
                
                if isinstance(value, Decimal):
                    value = float(value)
                
                existing = session.query(AirportIndicators).filter(
                    AirportIndicators.indicator_id == indicator.id,
                    AirportIndicators.airport_id == airport.id,
                    AirportIndicators.month == month_enum,
                    AirportIndicators.year == year
                ).first()
                
                if existing:
                    existing.value = value
                    total_updated += 1
                else:
                    airport_ind = AirportIndicators(
                        indicator_id=indicator.id,
                        airport_id=airport.id,
                        month=month_enum,
                        year=year,
                        value=value
                    )
                    session.add(airport_ind)
                    total_imported += 1
                
                if (total_imported + total_updated) % 50 == 0:
                    session.flush()
            
            session.commit()
            
            return {
                'success': True,
                'message': f'Импорт завершен. Добавлено: {total_imported}, Обновлено: {total_updated}',
                'imported': total_imported,
                'updated': total_updated
            }
            
        except Exception as e:
            session.rollback()
            return {
                'success': False,
                'message': f'Ошибка при импорте данных аэропорта: {str(e)}'
            }