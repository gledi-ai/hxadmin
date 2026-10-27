from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar

from fastapi import FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from demos.tables.auth import DEMO_EMAIL, DEMO_PASSWORD, authenticate, current_user
from demos.tables.models import ExchangeRate, Product, StockMove, Warehouse
from demos.tables.seed import seed
from demos.tables.tables import metadata
from hxadmin import BadgeTone, HxAdmin, ModelView

DB_PATH = Path(__file__).parent / "demo.db"
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async with sessionmaker() as session:
        await seed(session)
    yield
    await engine.dispose()


app = FastAPI(title="Inventory demo (Core tables)", lifespan=lifespan)
# Both demos run on 127.0.0.1, and cookies ignore the port, so each needs its own cookie name.
app.add_middleware(
    SessionMiddleware,
    secret_key="demo-only-not-a-secret",  # noqa: S106
    session_cookie="hxadmin_demo_tables_session",
    https_only=False,
)
admin = HxAdmin(
    app,
    session=get_session,
    auth=current_user,
    title="Inventory admin",
    login_url="/login",
    logout_url="/logout",
)
LOGIN_NOTE = f"Demo account: {DEMO_EMAIL}, password {DEMO_PASSWORD!r}."


@app.get("/login", response_model=None)
async def login_form(request: Request) -> HTMLResponse | RedirectResponse:
    if "user" in request.session:
        return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
    return admin.render_login(request, note=LOGIN_NOTE)


@app.post("/login", response_model=None)
async def login(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    email = str(form.get("username", "")).strip()
    if not authenticate(email, str(form.get("password", ""))):
        return admin.render_login(
            request,
            error="Wrong e-mail or password.",
            username=email,
            note=LOGIN_NOTE,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session.clear()
    request.session["user"] = email
    return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


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
