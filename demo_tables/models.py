from sqlalchemy.orm import DeclarativeBase

from demo_tables.tables import exchange_rates, metadata, products, stock_moves, warehouses


class Base(DeclarativeBase):
    metadata = metadata


class Warehouse(Base):
    __table__ = warehouses


class Product(Base):
    __table__ = products


class StockMove(Base):
    __table__ = stock_moves


class ExchangeRate(Base):
    __table__ = exchange_rates
    __mapper_args__ = {"primary_key": [exchange_rates.c.currency]}  # noqa: RUF012
