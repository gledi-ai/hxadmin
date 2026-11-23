from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, relationship

from demos.tables.tables import exchange_rates, metadata, products, stock_moves, warehouses


class Base(DeclarativeBase):
    metadata = metadata


class Warehouse(Base):
    __table__ = warehouses
    name: Mapped[str] = column_property(warehouses.c.name)


class Product(Base):
    __table__ = products
    name: Mapped[str] = column_property(products.c.name)


class StockMove(Base):
    __table__ = stock_moves
    product: Mapped[Product] = relationship()
    warehouse: Mapped[Warehouse] = relationship()


class ExchangeRate(Base):
    __table__ = exchange_rates
    __mapper_args__ = {"primary_key": [exchange_rates.c.currency]}  # noqa: RUF012
