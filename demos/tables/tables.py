import enum

from sqlalchemy import Column, Date, Enum, ForeignKey, Integer, MetaData, Numeric, String, Table

metadata = MetaData()


class MoveKind(enum.StrEnum):
    receipt = "receipt"
    shipment = "shipment"
    adjustment = "adjustment"


warehouses = Table(
    "warehouses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False, unique=True),
    Column("city", String, nullable=False),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sku", String, nullable=False, unique=True),
    Column("name", String, nullable=False),
    Column("price", Numeric(10, 2), nullable=False),
    Column("currency", String(3), nullable=False, default="EUR"),
)

stock_moves = Table(
    "stock_moves",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("product_id", ForeignKey("products.id"), nullable=False),
    Column("warehouse_id", ForeignKey("warehouses.id"), nullable=False),
    Column("kind", Enum(MoveKind), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("moved_on", Date, nullable=False),
)

exchange_rates = Table(
    "exchange_rates",
    metadata,
    Column("currency", String(3), nullable=False, unique=True),
    Column("per_eur", Numeric(12, 6), nullable=False),
)
