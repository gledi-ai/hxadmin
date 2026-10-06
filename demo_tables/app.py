from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from demo_tables.models import ExchangeRate, Product, StockMove, Warehouse
from demo_tables.seed import seed
from demo_tables.tables import metadata
from hxadmin import BadgeTone, HxAdmin, ModelView

DB_PATH = Path(__file__).parent / "demo_tables.db"
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


def dev_user() -> dict[str, str]:
    return {"name": "dev"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async with sessionmaker() as session:
        await seed(session)
    yield
    await engine.dispose()


app = FastAPI(title="Inventory demo (Core tables)", lifespan=lifespan)
admin = HxAdmin(app, session=get_session, auth=dev_user, title="Inventory admin")


@admin.register
class WarehouseView(ModelView[Warehouse]):
    model = Warehouse
    category = "Inventory"
    icon = "warehouse"
    searchable = ("name", "city")


@admin.register
class ProductView(ModelView[Product]):
    model = Product
    category = "Inventory"
    icon = "package"
    searchable = ("sku", "name")
    default_sort = ("sku", "asc")
    export_formats = ("csv", "xlsx")


@admin.register
class StockMoveView(ModelView[StockMove]):
    model = StockMove
    name = "Stock move"
    category = "Inventory"
    icon = "arrow-left-right"
    default_sort = ("moved_on", "desc")
    list_filters = ("kind", "warehouse_id", "moved_on")
    badges: ClassVar[Mapping[str, Mapping[str, BadgeTone]]] = {
        "kind": {"receipt": "success", "shipment": "accent", "adjustment": "warning"}
    }


@admin.register
class ExchangeRateView(ModelView[ExchangeRate]):
    model = ExchangeRate
    name = "Exchange rate"
    category = "Reference"
    icon = "coins"
    default_sort = ("currency", "asc")
