# importers/data_importer.py
from decimal import Decimal
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.orm import sessionmaker
from db.database import get_session, engine
from db.models.entities import (
    Airline, Airport, Indicator, Shipping, Route,
    AirlineIndicators, AirportIndicators
)
from db.models.enums import ShippingRegularity, RouteType, Months
from services import journal_service as journal
from utils.constants import GA12_DETAIL_TON_PARENT
import time


def _exact_decimal(value):
    """Значение отчётной строки как `Decimal`.

    Приведения к `float` здесь больше нет. Оно стояло прямо перед записью в
    колонку, объявленную десятичной, и обесценивало разбор: парсеры аккуратно
    строят `Decimal` из текста бланка, а в базу уходило двоичное приближение
    (BUG-4). Значения не из парсеров переводятся через `str`, чтобы не занести
    ту же ошибку окольным путём: `Decimal(0.1)` даёт 0.1000000000000000055…
    """
    if value is None or isinstance(value, Decimal):
        return value
    return Decimal(str(value))


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
    def _link_detail_indicators(cls, session) -> None:
        """Связывает детализацию тоннокилометража с родительской строкой бланка.

        parent_id нужен своду 12-ГА для подраздела «в том числе», а парсеры его не
        передают. Вызывается после создания всех показателей файла: родитель может
        быть создан в этом же импорте.
        """
        parent_ids = {
            code: ind_id
            for code, ind_id in session.query(Indicator.code, Indicator.id).filter(
                Indicator.code.in_(sorted(set(GA12_DETAIL_TON_PARENT.values())))
            )
        }
        if not parent_ids:
            return

        details = session.query(Indicator).filter(
            Indicator.code.in_(list(GA12_DETAIL_TON_PARENT)),
            Indicator.parent_id.is_(None),
        )
        for detail in details:
            parent_id = parent_ids.get(GA12_DETAIL_TON_PARENT[detail.code])
            if parent_id is not None:
                detail.parent_id = parent_id

    @classmethod
    def _resolve_indicators(cls, session, data: dict) -> dict:
        """Показатели файла: найденные в справочнике либо созданные.

        Блок был скопирован в обе ветки импорта дословно, вместе с ошибкой
        приоритета операторов в подстановке кода (BUG-1).
        """
        indicators_map = {}

        # Справочник показателей читается один раз: прежде на каждую строку файла
        # уходило по одному-двум отдельным запросам (PERF-3).
        by_code = {}
        by_name = {}
        for row in session.query(Indicator).all():
            if row.code:
                by_code.setdefault(row.code, row)
            if row.name:
                by_name.setdefault(row.name, row)

        for indicator_data in data.get('indicators', []):
            code = indicator_data.get('indicator_code') or indicator_data.get('code')
            name = indicator_data.get('indicator_name') or indicator_data.get('name')
            measure = indicator_data.get('measure', '')

            if not code and not name:
                continue

            indicator = by_code.get(code) if code else None

            # Поиск по названию — только когда кода нет вовсе. Названия строк в
            # бланке повторяются: «Самолето-километры» стоит и в регулярных
            # перевозках (965), и в нерегулярных (965н), «Налет часов» — ещё и в
            # некоммерческих (356нк). С поиском по названию строка 965н находила
            # уже созданный показатель 965, сама в справочнике не заводилась, а её
            # значения уходили под чужой код (DATA-8).
            if not indicator and not code and name:
                indicator = by_name.get(name)

            if not indicator:
                # Скобки обязательны: `code or name[:10] if name else 'UNK'` Python
                # читает как `(code or name[:10]) if name else 'UNK'`, то есть при
                # пустом имени отбрасывал код и подставлял 'UNK'. Второй такой
                # показатель ронял импорт файла по уникальному ключу кода.
                indicator = Indicator(
                    code=code or (name[:10] if name else 'UNK'),
                    name=name or code,
                    measure=measure,
                )
                session.add(indicator)
                session.flush()
                # Созданный показатель попадает в те же словари: следующая строка
                # файла с тем же кодом должна найти его, а не завести второй.
                by_code.setdefault(indicator.code, indicator)
                by_name.setdefault(indicator.name, indicator)

            indicators_map[(code, name)] = indicator

        cls._link_detail_indicators(session)
        return indicators_map

    @classmethod
    def _import_airline_data(cls, session, data: dict) -> dict:
        """Импорт данных для авиакомпаний"""
        try:
            indicators_map = cls._resolve_indicators(session, data)

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
            
            month_enum, year, period_error = cls._resolve_period(data)
            if period_error:
                return period_error

            total_imported = 0
            total_updated = 0

            # Справочники читаются один раз до цикла: рейсов и видов маршрута в
            # пределах файла считанные единицы, а поиск шёл на каждую строку
            # отдельным запросом (PERF-3).
            routes = cls._route_index(session)
            shippings = cls._shipping_index(session, airline.id)
            existing_rows = cls._existing_airline_rows(session, airline.id, month_enum, year)
            touched: set = set()

            for indicator_data in data.get('indicators', []):
                code = indicator_data.get('indicator_code') or indicator_data.get('code')
                name = indicator_data.get('indicator_name') or indicator_data.get('name')

                indicator = indicators_map.get((code, name))
                if not indicator:
                    continue

                route_type = cls._as_enum(
                    RouteType, indicator_data.get('route_type'), RouteType.local
                )
                regularity = cls._as_enum(
                    ShippingRegularity, indicator_data.get('regularity'), ShippingRegularity.regular
                )

                route = routes.get((route_type, regularity))
                if route is None:
                    route = Route(type=route_type, regularity=regularity)
                    session.add(route)
                    session.flush()
                    routes[(route_type, regularity)] = route

                shipping = shippings.get(route.id)
                if shipping is None:
                    shipping = Shipping(airline_id=airline.id, route_id=route.id)
                    session.add(shipping)
                    session.flush()
                    shippings[route.id] = shipping

                value = indicator_data.get('value')
                if value is None:
                    continue

                value = _exact_decimal(value)

                key = (indicator.id, shipping.id)
                touched.add(key)
                existing = existing_rows.get(key)
                if existing is not None:
                    # Тот же ключ второй раз в одном файле обновляет запись, а не
                    # добавляет вторую: прежде дубль внутри присланного файла ронял
                    # импорт целиком по уникальному ключу.
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
                    existing_rows[key] = airline_ind
                    total_imported += 1

            total_removed = cls._drop_vanished_rows(session, existing_rows, touched)

            journal.record_safely(
                session,
                kind=journal.KIND_IMPORT,
                source_file=data.get('source_file'),
                entity_type='airline',
                entity_id=airline.id,
                entity_name=airline.name.strip(),
                month=month_enum,
                year=year,
                imported=total_imported,
                updated=total_updated,
                removed=total_removed,
            )

            session.commit()

            return cls._import_result(total_imported, total_updated, total_removed)

        except Exception as e:
            return cls._failure(session, e, "авиакомпании")

    @staticmethod
    def _drop_vanished_rows(session, existing_rows: dict, touched: set) -> int:
        """Убирает строки периода, которых нет в новом файле (DATA-5).

        Импорт работает как upsert, поэтому исправленный отчёт, где ошибочная
        строка удалена, оставлял прежнее значение в базе: свод показывал смесь
        двух версий отчёта, и понять, какая из них в базе, было нечем.

        Отчёт за период считается полным: что не пришло — того за этот период у
        предприятия нет. Удаление идёт в той же транзакции, что и запись, и
        попадает в журнал вместе с ней; перед необратимой частью операции окно
        снимает копию базы (FUNC-6).
        """
        vanished = [row for key, row in existing_rows.items() if key not in touched]
        for row in vanished:
            session.delete(row)
        return len(vanished)

    @staticmethod
    def _as_enum(enum_cls, raw, default):
        """Член перечисления по имени или подписи; при неизвестном значении — умолчание."""
        if isinstance(raw, enum_cls):
            return raw
        for member in enum_cls:
            if member.name == raw or member.value == raw:
                return member
        return default

    @staticmethod
    def _route_index(session) -> dict:
        """Виды рейса по паре (тип маршрута, регулярность) — одним запросом."""
        return {(route.type, route.regularity): route for route in session.query(Route).all()}

    @staticmethod
    def _shipping_index(session, airline_id: int) -> dict:
        """Рейсы предприятия по `route_id` — одним запросом."""
        rows = session.query(Shipping).filter(Shipping.airline_id == airline_id).all()
        return {shipping.route_id: shipping for shipping in rows}

    @staticmethod
    def _existing_airline_rows(session, airline_id: int, month_enum, year: int) -> dict:
        """Строки отчётности предприятия за период — одним запросом вместо одного на строку."""
        rows = (
            session.query(AirlineIndicators)
            .join(Shipping, AirlineIndicators.shipping_id == Shipping.id)
            .filter(
                Shipping.airline_id == airline_id,
                AirlineIndicators.month == month_enum,
                AirlineIndicators.year == year,
            )
            .all()
        )
        return {(row.indicator_id, row.shipping_id): row for row in rows}

    @staticmethod
    def _existing_airport_rows(session, airport_id: int, month_enum, year: int) -> dict:
        """То же для аэропортов: рейсов в 15-ГА нет, ключ — только показатель."""
        rows = (
            session.query(AirportIndicators)
            .filter(
                AirportIndicators.airport_id == airport_id,
                AirportIndicators.month == month_enum,
                AirportIndicators.year == year,
            )
            .all()
        )
        return {row.indicator_id: row for row in rows}

    @classmethod
    def _failure(cls, session, error: Exception, whose: str) -> dict:
        """Разбор ошибки импорта — общий для обеих веток.

        Блокировка базы пробрасывается наверх: там её ждёт `_retry_import` с тремя
        попытками и нарастающей паузой. Ветка аэропортов ловила всё подряд общим
        `except Exception`, поэтому механизм повтора, написанный ради устойчивости
        SQLite к блокировкам, для формы 15-ГА не срабатывал ни разу (BUG-23).
        """
        session.rollback()

        if isinstance(error, OperationalError):
            if "database is locked" in str(error):
                raise error
            return {'success': False, 'message': f'Ошибка базы данных: {error}'}

        if isinstance(error, IntegrityError):
            return {'success': False, 'message': f'Ошибка целостности данных: {error}'}

        return {
            'success': False,
            'message': f'Неожиданная ошибка при импорте данных {whose}: {error}',
        }

    @classmethod
    def _import_airport_data(cls, session, data: dict) -> dict:
        """Импорт данных для аэропортов"""
        try:
            indicators_map = cls._resolve_indicators(session, data)

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
            
            month_enum, year, period_error = cls._resolve_period(data)
            if period_error:
                return period_error

            total_imported = 0
            total_updated = 0

            # Строки периода читаются одним запросом, а не по одному на показатель.
            existing_rows = cls._existing_airport_rows(session, airport.id, month_enum, year)
            touched: set = set()

            for indicator_data in data.get('indicators', []):
                code = indicator_data.get('indicator_code') or indicator_data.get('code')
                name = indicator_data.get('indicator_name') or indicator_data.get('name')

                indicator = indicators_map.get((code, name))
                if not indicator:
                    continue

                value = indicator_data.get('value')
                if value is None:
                    continue
                
                value = _exact_decimal(value)

                touched.add(indicator.id)
                existing = existing_rows.get(indicator.id)
                if existing is not None:
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
                    existing_rows[indicator.id] = airport_ind
                    total_imported += 1

            total_removed = cls._drop_vanished_rows(session, existing_rows, touched)

            journal.record_safely(
                session,
                kind=journal.KIND_IMPORT,
                source_file=data.get('source_file'),
                entity_type='airport',
                entity_id=airport.id,
                entity_name=airport.name.strip(),
                month=month_enum,
                year=year,
                imported=total_imported,
                updated=total_updated,
                removed=total_removed,
            )

            session.commit()

            return cls._import_result(total_imported, total_updated, total_removed)

        except Exception as e:
            return cls._failure(session, e, "аэропорта")

    @staticmethod
    def _resolve_period(data: dict):
        """Месяц и год разобранного файла. Умолчаний нет — только то, что в данных.

        Прежде отсутствующий или нераспознанный месяц превращался здесь в
        Months.January, а год — в 2025, уже после того как парсер делал ровно то же
        самое. Импорт работает как upsert по ключу (показатель, рейс, месяц, год),
        поэтому подстановка не просто помечала период неверно, а затирала настоящую
        отчётность подставленного месяца (DATA-2).

        Возвращает (month_enum, year, error): error заполнен, если период не определён.
        """
        month_name = data.get('month')
        year = data.get('year')
        month_enum = next((m for m in Months if m.name == month_name), None)
        if month_enum is None or not year:
            return None, None, {
                'success': False,
                'message': (
                    f'Отчётный период не определён (месяц: {month_name!r}, '
                    f'год: {year!r}). Импорт отменён, чтобы не затереть данные '
                    'другого периода.'
                ),
            }
        return month_enum, int(year), None

    @staticmethod
    def _import_result(total_imported: int, total_updated: int, total_removed: int = 0) -> dict:
        """Итог импорта. Ноль записей — отказ, а не успех.

        Разбор, не нашедший ни одного показателя, возвращал success=True с
        «Добавлено: 0, Обновлено: 0», и окно показывало зелёное «Импорт завершён».
        Пользователь был уверен, что отчёт загружен, хотя в базу не попало ничего;
        обнаружиться это могло разве что при сверке итогов (DATA-4).
        """
        if total_imported == 0 and total_updated == 0:
            return {
                'success': False,
                'message': 'Ни одного показателя не прочитано — в базу не записано ничего.',
                'imported': 0,
                'updated': 0,
                'removed': 0,
            }
        message = f'Импорт завершен. Добавлено: {total_imported}, Обновлено: {total_updated}'
        if total_removed:
            # Про удаление сообщается прямо: отчёт заменил период целиком, и
            # пользователь должен видеть это, а не обнаружить потом в своде.
            message += (
                f'. Удалено строк, которых нет в новом отчёте: {total_removed}'
            )
        return {
            'success': True,
            'message': message,
            'imported': total_imported,
            'updated': total_updated,
            'removed': total_removed,
        }