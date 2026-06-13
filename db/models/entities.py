from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base
from sqlalchemy import ForeignKey, Integer, String, ForeignKey, Float, DateTime, DECIMAL
from datetime import datetime
from db.models.enums import RouteType, UserPosition, ShippingRegularity, Months

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(25), unique=True)
    position: Mapped[UserPosition]
    password_hash: Mapped[str]

class Airport(Base):
    __tablename__ = 'airports'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)
    name: Mapped[str] = mapped_column(String(25))
    locality_id: Mapped[int] = mapped_column(ForeignKey('airport_localities.id'))
    locality: Mapped["Locality"] = relationship("Locality", back_populates="airports")

    indicators: Mapped[List["AirportIndicators"]] = relationship("AirportIndicators", back_populates="airport", cascade="all, delete-orphan")

class Locality(Base):
    __tablename__ = 'airport_localities'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)

    airports = relationship("Airport", back_populates="locality", cascade="all, delete-orphan")


class Airline(Base):
    __tablename__ = 'airlines'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)
    name: Mapped[str] = mapped_column(String(50))

    shippings = relationship("Shipping", back_populates="airline", cascade="all, delete-orphan")

class Shipping(Base):
    __tablename__ = 'shipping'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(ForeignKey('routes.id'))
    route: Mapped["Route"] = relationship("Route")
    airline_id: Mapped[int] = mapped_column(ForeignKey('airlines.id'))
    airline: Mapped["Airline"] = relationship("Airline", back_populates="shippings")

    indicators: Mapped[List["AirlineIndicators"]] = relationship("AirlineIndicators", back_populates="shipping")

class Route(Base):
    __tablename__ = 'routes'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    type: Mapped[RouteType]
    regularity: Mapped[ShippingRegularity]

class AirlineIndicators(Base):
    __tablename__ = 'airlineInd'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey('indicators.id'))
    indicator: Mapped["Indicator"] = relationship("Indicator")
    shipping_id: Mapped[int] = mapped_column(ForeignKey('shipping.id'))
    shipping: Mapped["Shipping"] = relationship("Shipping", back_populates="indicators")
    month: Mapped[Months]
    year: Mapped[int] = mapped_column(Integer, default=2025)
    value: Mapped[Decimal] = mapped_column(DECIMAL)

class Indicator(Base):
    __tablename__ = 'indicators'

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    measure: Mapped[str] = mapped_column(String(20))
    # Детализация показателя (напр. 450пас → родитель 450 «Выполненный тоннокилометраж»)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey('indicators.id'), nullable=True)
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

    id: Mapped[int] = mapped_column(primary_key=True, unique=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey('indicators.id'))
    indicator: Mapped["Indicator"] = relationship("Indicator")
    airport_id: Mapped[int] = mapped_column(ForeignKey('airports.id'))
    airport: Mapped["Airport"] = relationship("Airport", back_populates="indicators")
    month: Mapped[Months]
    year: Mapped[int] = mapped_column(Integer, default=2025)
    value: Mapped[Decimal] = mapped_column(DECIMAL)
