from datetime import date
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from demo_tables.tables import MoveKind, exchange_rates, products, stock_moves, warehouses


async def seed(session: AsyncSession) -> None:
    if await session.scalar(select(products.c.id).limit(1)) is not None:
        return
    await session.execute(
        insert(warehouses),
        [{"name": "North", "city": "Oslo"}, {"name": "South", "city": "Lisbon"}],
    )
    await session.execute(
        insert(products),
        [
            {"sku": "KB-01", "name": "Keyboard", "price": Decimal("49.90")},
            {"sku": "MS-02", "name": "Mouse", "price": Decimal("19.50")},
            {"sku": "MN-27", "name": "27in monitor", "price": Decimal("229.00")},
            {"sku": "CB-USB", "name": "USB-C cable", "price": Decimal("7.99")},
        ],
    )
    await session.execute(
        insert(stock_moves),
        [
            {
                "product_id": 1,
                "warehouse_id": 1,
                "kind": MoveKind.receipt,
                "quantity": 40,
                "moved_on": date(2026, 9, 1),
            },
            {
                "product_id": 2,
                "warehouse_id": 1,
                "kind": MoveKind.receipt,
                "quantity": 80,
                "moved_on": date(2026, 9, 1),
            },
            {
                "product_id": 3,
                "warehouse_id": 2,
                "kind": MoveKind.receipt,
                "quantity": 12,
                "moved_on": date(2026, 9, 3),
            },
            {
                "product_id": 1,
                "warehouse_id": 1,
                "kind": MoveKind.shipment,
                "quantity": -5,
                "moved_on": date(2026, 9, 10),
            },
            {
                "product_id": 4,
                "warehouse_id": 2,
                "kind": MoveKind.receipt,
                "quantity": 200,
                "moved_on": date(2026, 9, 12),
            },
            {
                "product_id": 3,
                "warehouse_id": 2,
                "kind": MoveKind.adjustment,
                "quantity": -1,
                "moved_on": date(2026, 9, 20),
            },
        ],
    )
    await session.execute(
        insert(exchange_rates),
        [
            {"currency": "USD", "per_eur": Decimal("1.09")},
            {"currency": "GBP", "per_eur": Decimal("0.85")},
            {"currency": "CHF", "per_eur": Decimal("0.94")},
        ],
    )
    await session.commit()
