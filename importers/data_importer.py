# importers/data_importer.py
from decimal import Decimal
from typing import Any
from sqlalchemy.exc import OperationalError, IntegrityError
from db.database import get_session
from db.models.entities import (
    Airline, Airport, Indicator, Locality, Shipping, Route,
    AirlineIndicators, AirportIndicators
)
from db.models.enums import ShippingRegularity, RouteType, Months
from services import journal_service as journal
from services.import_outcome import ImportOutcome, failure
from utils.constants import GA12_DETAIL_TON_PARENT
from utils.entity_codes import unique_entity_code
from utils.entity_names import normalized_entity_name
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
    def _route_import(cls, session, data: dict) -> ImportOutcome:
        """Маршрутизация: сначала явный data_type, иначе по составу payload (без ложного срабатывания на 15-ГА)."""
        dt = data.get("data_type") or data.get("entity_type")
        if dt == "airport":
            return cls._import_airport_data(session, data)
        if dt == "airline":
            return cls._import_airline_data(session, data)
        if "airline" in data:
            return cls._import_airline_data(session, data)
        if "airport" in data or "airports" in data:
            return cls._import_airport_data(session, data)
        return failure(f"Неизвестный тип данных: {dt}")

    @classmethod
    def import_data(cls, session, data: dict) -> ImportOutcome:
        """Основной метод импорта данных"""
        try:
            return cls._route_import(session, data)

        except OperationalError as e:
            if "database is locked" in str(e):
                return cls._retry_import(data, max_retries=3)
            raise
    
    @classmethod
    def _retry_import(cls, data: dict, max_retries: int = 3) -> ImportOutcome:
        """Повторяет импорт при блокировке базы данных"""
        for attempt in range(max_retries):
            try:
                time.sleep(0.5 * (attempt + 1))
                with get_session() as session:
                    return cls._route_import(session, data)
            except OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    continue
                return failure(f'Ошибка импорта после {max_retries} попыток: {str(e)}')
            except Exception as e:
                return failure(f'Ошибка при импорте: {str(e)}')
        return failure('Не удалось выполнить импорт')

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
    def _resolve_indicators(cls, session, indicators: list) -> dict:
        """Показатели файла: найденные в справочнике либо созданные.

        Блок был скопирован в обе ветки импорта дословно, вместе с ошибкой
        приоритета операторов в подстановке кода (BUG-1).

        Принимает сами строки показателей, а не разобранный файл целиком:
        сводный бланк 15-ГА везёт по набору строк на каждый аэропорт, и
        справочник должен читаться один раз на файл, а не на аэропорт.
        """
        indicators_map = {}

        # Справочник показателей читается один раз: прежде на каждую строку файла
        # уходило по одному-двум отдельным запросам (PERF-3).
        by_code: dict[str, Indicator] = {}
        by_name: dict[str, Indicator] = {}
        for row in session.query(Indicator).all():
            if row.code:
                by_code.setdefault(row.code, row)
            if row.name:
                by_name.setdefault(row.name, row)

        for indicator_data in indicators:
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
    def _import_airline_data(cls, session, data: dict) -> ImportOutcome:
        """Импорт данных для авиакомпаний"""
        try:
            indicators_map = cls._resolve_indicators(session, data.get('indicators', []))

            created: list[str] = []
            airline, error = cls._resolve_airline(session, data, created)
            if airline is None:
                return error or failure('Авиакомпания отчёта не определена.')

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

            result = cls._import_result(
                total_imported, total_updated, total_removed,
                created=created, register='авиакомпаний',
            )
            if not result.success:
                # Ни одной строки не прочитано — заводить под неё авиакомпанию не
                # за что: иначе отказ оставлял бы в справочнике запись из файла,
                # который в базу не попал.
                session.rollback()
                return result

            session.commit()
            return result

        except Exception as e:
            return cls._failure(session, e, "авиакомпании")

    @classmethod
    def _resolve_airline(cls, session, data: dict,
                         created: list[str]) -> tuple[Airline | None, ImportOutcome | None]:
        """Авиакомпания отчёта: по id, по названию, иначе заводится.

        Название в отчёте — уставное («Акционерное общество "Авиакомпания
        "АЛРОСА"»), в справочнике — короткое («АО Авиакомпания АЛРОСА»): сравнение
        идёт по приведённому виду, иначе рядом с заведённой записью появилась бы
        вторая и отчётность одной авиакомпании разошлась бы по двум строкам свода.

        Незнакомая авиакомпания заводится, как и аэропорт сводного бланка: годовой
        комплект приходит сразу на несколько предприятий, и отклонять файл целиком
        из-за того, что одного из них ещё нет в справочнике, значило бы требовать
        завести его вручную по названию из того же файла. Заведённые записи
        перечисляются в отчёте об импорте: молча пополнять справочник нельзя.
        """
        airline_data = data.get('airline', {})
        airline_id = data.get('entity_id') or airline_data.get('id')
        if airline_id:
            airline = session.get(Airline, airline_id)
            if not airline:
                return None, failure(f'Авиакомпания с ID {airline_id} не найдена')
            return airline, None

        name = (airline_data.get('name') or '').strip()
        if not name:
            return None, failure(
                'Предприятие не выбрано, а в файле авиакомпания не названа — '
                'импорт отменён, чтобы отчётность не ушла в чужую строку.'
            )

        airline = cls._airline_by_name(session, name)
        if airline:
            return airline, None

        airline = Airline(
            code=cls._free_airline_code(session, name, airline_data.get('code')),
            name=name,
        )
        session.add(airline)
        session.flush()
        created.append(name)
        return airline, None

    @staticmethod
    def _airline_by_name(session, name: str) -> Airline | None:
        """Запись справочника с тем же названием — посимвольно или по приведённому виду."""
        airlines = session.query(Airline).all()
        for airline in airlines:
            if (airline.name or '').strip() == name:
                return airline
        wanted = normalized_entity_name(name)
        for airline in airlines:
            if wanted and normalized_entity_name(airline.name) == wanted:
                return airline
        return None

    @staticmethod
    def _free_airline_code(session, name: str, preferred: str | None) -> str:
        codes = {code for (code,) in session.query(Airline.code) if code}
        return unique_entity_code(name, codes, preferred=preferred)

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
    def _failure(cls, session, error: Exception, whose: str) -> ImportOutcome:
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
            return failure(f'Ошибка базы данных: {error}')

        if isinstance(error, IntegrityError):
            return failure(f'Ошибка целостности данных: {error}')

        return failure(f'Неожиданная ошибка при импорте данных {whose}: {error}')

    @staticmethod
    def _airport_blocks(data: dict) -> list[dict[str, Any]]:
        """Отчётность файла, разложенная по аэропортам.

        Обычный бланк 15-ГА заполняется на один аэропорт, сводный — на всё
        предприятие сразу: блок самого предприятия и по блоку на каждый его
        аэропорт. Обе формы приводятся к одному виду, чтобы запись шла одним
        путём: разница между ними — только в числе блоков.
        """
        blocks = data.get('airports')
        if blocks:
            return [dict(block) for block in blocks]

        airport_data = data.get('airport', {})
        return [{
            'name': airport_data.get('name', ''),
            'id': data.get('entity_id') or airport_data.get('id'),
            'parent_name': None,
            'indicators': data.get('indicators', []),
        }]

    @classmethod
    def _import_airport_data(cls, session, data: dict) -> ImportOutcome:
        """Импорт данных для аэропортов (одного или всех аэропортов предприятия)."""
        try:
            month_enum, year, period_error = cls._resolve_period(data)
            if period_error:
                return period_error

            blocks = cls._airport_blocks(data)
            indicators_map = cls._resolve_indicators(
                session, [row for block in blocks for row in block.get('indicators', [])]
            )

            airports: dict[str, Airport] = {}
            created: list[str] = []
            for block in blocks:
                airport, error = cls._resolve_airport(session, block, created)
                if airport is None:
                    return error or failure('Аэропорт блока не определён.')
                airports[block.get('name', '')] = airport
                block['airport'] = airport

            cls._link_airport_parents(blocks, airports)

            total_imported = 0
            total_updated = 0
            total_removed = 0

            for block in blocks:
                imported, updated, removed = cls._write_airport_block(
                    session, block, indicators_map, month_enum, year
                )
                total_imported += imported
                total_updated += updated
                total_removed += removed

                journal.record_safely(
                    session,
                    kind=journal.KIND_IMPORT,
                    source_file=data.get('source_file'),
                    entity_type='airport',
                    entity_id=block['airport'].id,
                    entity_name=block['airport'].name.strip(),
                    month=month_enum,
                    year=year,
                    imported=imported,
                    updated=updated,
                    removed=removed,
                )

            result = cls._import_result(
                total_imported, total_updated, total_removed, created=created
            )
            if not result.success:
                # Ни одной строки не прочитано — заводить под неё аэропорты не за
                # что: иначе отказ оставлял бы в справочнике записи из файла,
                # который в базу не попал.
                session.rollback()
                return result

            session.commit()
            return result

        except Exception as e:
            return cls._failure(session, e, "аэропорта")

    @classmethod
    def _resolve_airport(cls, session, block: dict,
                         created: list[str]) -> tuple[Airport | None, ImportOutcome | None]:
        """Аэропорт блока: по id, по названию, иначе заводится.

        Сводный бланк называет тридцать с лишним аэропортов, и требовать, чтобы
        все они уже стояли в справочнике, значило бы отклонять первый же
        присланный комплект целиком. Заведённые записи перечисляются в отчёте об
        импорте: молча пополнять справочник тоже нельзя.
        """
        airport_id = block.get('id')
        if airport_id:
            airport = session.get(Airport, airport_id)
            if not airport:
                return None, failure(f'Аэропорт с ID {airport_id} не найден')
            return airport, None

        name = (block.get('name') or '').strip()
        if not name:
            return None, failure(
                'В файле есть блок без названия аэропорта — импорт отменён, '
                'чтобы отчётность не ушла в чужую строку.'
            )

        airport = session.query(Airport).filter(Airport.name == name).first()
        if airport:
            return airport, None

        airport = Airport(
            code=cls._free_airport_code(session, name),
            name=name,
            locality_id=cls._locality_id(session, name),
        )
        session.add(airport)
        session.flush()
        created.append(name)
        return airport, None

    @staticmethod
    def _free_airport_code(session, name: str) -> str:
        codes = {code for (code,) in session.query(Airport.code) if code}
        return unique_entity_code(name, codes)

    @staticmethod
    def _locality_id(session, name: str) -> int:
        """Населённый пункт для заводимого аэропорта.

        Бланк населённого пункта не называет, а колонка обязательна. Берётся
        название самого аэропорта: для «Алдана» или «Батагая» это и есть правда,
        а для предприятия — заметная заглушка, которую видно в справочнике и
        которую там же можно исправить.
        """
        locality = session.query(Locality).filter(Locality.name == name).first()
        if locality is None:
            locality = Locality(name=name)
            session.add(locality)
            session.flush()
        return locality.id

    @staticmethod
    def _link_airport_parents(blocks: list[dict], airports: dict[str, Airport]) -> None:
        """Проставляет предприятие, в состав которого входит аэропорт.

        Состав предприятия берётся из файла: он его и сдаёт. Ручная перестановка
        в справочниках держится ровно до следующей загрузки сводного бланка —
        иначе свод показывал бы не тот состав, что в присланном отчёте.
        """
        for block in blocks:
            parent_name = block.get('parent_name')
            if not parent_name:
                continue
            parent = airports.get(parent_name)
            if parent is None or parent.id == block['airport'].id:
                continue
            block['airport'].parent_id = parent.id

    @classmethod
    def _write_airport_block(cls, session, block: dict, indicators_map: dict,
                             month_enum, year: int) -> tuple[int, int, int]:
        """Строки одного аэропорта за период. Возвращает (добавлено, обновлено, удалено)."""
        airport = block['airport']
        imported = 0
        updated = 0

        # Строки периода читаются одним запросом, а не по одному на показатель.
        existing_rows = cls._existing_airport_rows(session, airport.id, month_enum, year)
        touched: set = set()

        for indicator_data in block.get('indicators', []):
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
                updated += 1
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
                imported += 1

        removed = cls._drop_vanished_rows(session, existing_rows, touched)
        return imported, updated, removed

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
            return None, None, failure(
                f'Отчётный период не определён (месяц: {month_name!r}, '
                f'год: {year!r}). Импорт отменён, чтобы не затереть данные '
                'другого периода.'
            )
        return month_enum, int(year), None

    @staticmethod
    def _import_result(total_imported: int, total_updated: int, total_removed: int = 0,
                       created: list[str] | None = None,
                       register: str = 'аэропортов') -> ImportOutcome:
        """Итог импорта. Ноль записей — отказ, а не успех.

        Разбор, не нашедший ни одного показателя, возвращал success=True с
        «Добавлено: 0, Обновлено: 0», и окно показывало зелёное «Импорт завершён».
        Пользователь был уверен, что отчёт загружен, хотя в базу не попало ничего;
        обнаружиться это могло разве что при сверке итогов (DATA-4).
        """
        if total_imported == 0 and total_updated == 0:
            return failure('Ни одного показателя не прочитано — в базу не записано ничего.')
        message = f'Импорт завершен. Добавлено: {total_imported}, Обновлено: {total_updated}'
        if total_removed:
            # Про удаление сообщается прямо: отчёт заменил период целиком, и
            # пользователь должен видеть это, а не обнаружить потом в своде.
            message += (
                f'. Удалено строк, которых нет в новом отчёте: {total_removed}'
            )
        if created:
            # Пополнение справочника называется поимённо: импорт заводит записи
            # сам, и узнавать об этом из справочника задним числом неправильно.
            message += f'. Заведены в справочнике {register}: ' + ', '.join(created)
        return ImportOutcome(
            success=True,
            message=message,
            imported=total_imported,
            updated=total_updated,
            removed=total_removed,
            created_entities=tuple(created or ()),
        )