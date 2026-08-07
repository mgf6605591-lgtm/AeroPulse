from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from datetime import datetime
from db.models.enums import RouteType, UserPosition, ShippingRegularity, Months
from db.models.types import ExactDecimal, MonthNumber

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(25), unique=True)
    position: Mapped[UserPosition]
    # Хеш scrypt в формате utils.passwords, а не сам пароль (SEC-1).
    password_hash: Mapped[str]
    # Учётки, чей открытый пароль перевела в хеш миграция, обязаны сменить его при
    # первом входе: прежнее значение известно всем, у кого есть клон репозитория (SEC-5).
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default='0'
    )

class Airport(Base):
    __tablename__ = 'airports'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)
    name: Mapped[str] = mapped_column(String(25))
    # RESTRICT: правка справочника населённых пунктов не должна стирать отчётность аэропорта
    locality_id: Mapped[int] = mapped_column(ForeignKey('airport_localities.id', ondelete='RESTRICT'))
    locality: Mapped["Locality"] = relationship("Locality", back_populates="airports")
    # Вывод из работы вместо удаления: запись остаётся вместе со всей отчётностью,
    # но не предлагается при выборе предприятия (SCH-10).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default='1')

    # Без каскада: аэропорт с отчётностью удалить нельзя, это запрещает БД
    # (ondelete='RESTRICT'). Удаление одной строки справочника не должно уносить
    # накопленные за годы отчёты — для этого есть is_active.
    indicators: Mapped[List["AirportIndicators"]] = relationship("AirportIndicators", back_populates="airport", passive_deletes="all")

class Locality(Base):
    __tablename__ = 'airport_localities'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)

    # Без каскада: удаление населённого пункта с аэропортами запрещает БД (ondelete='RESTRICT')
    airports = relationship("Airport", back_populates="locality", passive_deletes="all")


class Airline(Base):
    __tablename__ = 'airlines'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    # См. Airport.is_active — вывод предприятия из работы без потери истории (SCH-10).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default='1')

    # Без каскада: авиакомпания с рейсами удаляться не должна — за рейсами стоит
    # вся её отчётность (ondelete='RESTRICT' на shipping.airline_id).
    shippings = relationship("Shipping", back_populates="airline", passive_deletes="all")

class Shipping(Base):
    __tablename__ = 'shipping'
    __table_args__ = (
        Index('uq_shipping_airline_route', 'airline_id', 'route_id', unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(ForeignKey('routes.id', ondelete='RESTRICT'))
    route: Mapped["Route"] = relationship("Route")
    airline_id: Mapped[int] = mapped_column(ForeignKey('airlines.id', ondelete='RESTRICT'))
    airline: Mapped["Airline"] = relationship("Airline", back_populates="shippings")

    indicators: Mapped[List["AirlineIndicators"]] = relationship("AirlineIndicators", back_populates="shipping", cascade="all, delete-orphan", passive_deletes=True)

class Route(Base):
    __tablename__ = 'routes'
    __table_args__ = (
        Index('uq_routes_type_regularity', 'type', 'regularity', unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    type: Mapped[RouteType]
    regularity: Mapped[ShippingRegularity]

class AirlineIndicators(Base):
    __tablename__ = 'airlineInd'
    # Ключ отчётной строки: один показатель на рейс за месяц. Он же ускоряет
    # поиск существующей записи при импорте.
    __table_args__ = (
        Index('uq_airline_ind_period', 'indicator_id', 'shipping_id', 'month', 'year', unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey('indicators.id', ondelete='RESTRICT'))
    indicator: Mapped["Indicator"] = relationship("Indicator")
    shipping_id: Mapped[int] = mapped_column(ForeignKey('shipping.id', ondelete='CASCADE'))
    shipping: Mapped["Shipping"] = relationship("Shipping", back_populates="indicators")
    month: Mapped[Months] = mapped_column(MonthNumber)
    year: Mapped[int] = mapped_column(Integer, default=2025)
    value: Mapped[Decimal] = mapped_column(ExactDecimal)

class Indicator(Base):
    __tablename__ = 'indicators'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    measure: Mapped[str] = mapped_column(String(20))
    # Детализация показателя (напр. 450пас → родитель 450 «Выполненный тоннокилометраж»)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey('indicators.id', ondelete='SET NULL'), nullable=True)
    parent: Mapped[Optional["Indicator"]] = relationship(
        "Indicator",
        remote_side="Indicator.id",
        back_populates="children",
    )
    children: Mapped[List["Indicator"]] = relationship(
        "Indicator",
        back_populates="parent",
    )

class AirportIndicators(Base):
    __tablename__ = 'airportInd'
    # Ключ отчётной строки: один показатель на аэропорт за месяц.
    __table_args__ = (
        Index('uq_airport_ind_period', 'indicator_id', 'airport_id', 'month', 'year', unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey('indicators.id', ondelete='RESTRICT'))
    indicator: Mapped["Indicator"] = relationship("Indicator")
    airport_id: Mapped[int] = mapped_column(ForeignKey('airports.id', ondelete='RESTRICT'))
    airport: Mapped["Airport"] = relationship("Airport", back_populates="indicators")
    month: Mapped[Months] = mapped_column(MonthNumber)
    year: Mapped[int] = mapped_column(Integer, default=2025)
    value: Mapped[Decimal] = mapped_column(ExactDecimal)


class ImportLog(Base):
    """Журнал загрузок и удалений (FUNC-5).

    О происхождении данных не сохранялось ничего: имя файла упоминалось только в
    сообщении на экране. При расхождении цифр нельзя было установить, из какого
    файла пришло значение и не затёр ли его повторный импорт.

    Строка журнала не ссылается на предприятие внешним ключом: журнал должен
    пережить удаление того, о чём он рассказывает, — иначе он перестаёт быть
    журналом. По той же причине здесь хранится название, а не только id.
    """

    __tablename__ = 'import_log'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 'import' — загрузка файла, 'delete' — удаление записей пользователем,
    # 'replace' — строки периода, исчезнувшие из исправленного отчёта (DATA-5).
    kind: Mapped[str] = mapped_column(String(20))
    user: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    source_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entity_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    month: Mapped[Optional[Months]] = mapped_column(MonthNumber, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    imported: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
