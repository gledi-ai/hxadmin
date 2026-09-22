import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin.query import count_many

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin

logger = logging.getLogger("hxadmin")


@dataclass(frozen=True, slots=True)
class NavItem:
    label: str
    url: str
    icon: str | None
    active: bool


@dataclass(frozen=True, slots=True)
class NavGroup:
    label: str | None
    items: tuple[NavItem, ...]


def build_nav(admin: "HxAdmin", request: Request) -> list[NavGroup]:
    groups: dict[str | None, list[NavItem]] = {None: []}
    for view in admin.views.values():
        if not view.is_visible(request):
            continue
        url = admin.url(request, f"/{view.identity}/")
        item = NavItem(view.name_plural, url, view.icon, request.url.path.startswith(url))
        groups.setdefault(view.category, []).append(item)
    for page in admin.pages:
        if not page.in_nav:
            continue
        url = admin.url(request, page.path)
        item = NavItem(page.title, url, page.icon, request.url.path == url)
        groups.setdefault(page.category, []).append(item)
    return [NavGroup(label, tuple(items)) for label, items in groups.items() if items]


@dataclass(frozen=True, slots=True)
class DashboardCard:
    label: str
    url: str
    icon: str | None
    count: int | None


@dataclass(frozen=True, slots=True)
class DashboardGroup:
    label: str | None
    cards: tuple[DashboardCard, ...]


async def build_dashboard(
    admin: "HxAdmin", request: Request, session: AsyncSession
) -> list[DashboardGroup]:
    """One card per visible, accessible view, counted through its `get_query` in one query.

    A view whose query cannot be built, or a count query that fails, shows no count
    (the error goes to the `hxadmin` logger) instead of breaking the dashboard.
    """
    views = [v for v in admin.views.values() if v.is_visible(request) and v.is_accessible(request)]
    stmts: dict[str, Select[Any]] = {}
    for view in views:
        try:
            stmts[view.identity] = view.get_query(request)
        except Exception:
            logger.exception("Dashboard: get_query of %s failed", type(view).__name__)
    counts: dict[str, int] = {}
    try:
        counts = dict(zip(stmts, await count_many(session, list(stmts.values())), strict=True))
    except SQLAlchemyError:
        logger.exception("Dashboard: counting rows failed")
        await session.rollback()
    groups: dict[str | None, list[DashboardCard]] = {None: []}
    for view in views:
        url = admin.url(request, f"/{view.identity}/")
        groups.setdefault(view.category, []).append(
            DashboardCard(view.name_plural, url, view.icon, counts.get(view.identity))
        )
    return [DashboardGroup(label, tuple(cards)) for label, cards in groups.items() if cards]


def build_search_targets(admin: "HxAdmin", request: Request) -> list[NavItem]:
    """Searchable views offered by the top-bar search; `active` marks the current list."""
    targets: list[NavItem] = []
    for view in admin.views.values():
        if not (view.searchable and view.is_visible(request) and view.is_accessible(request)):
            continue
        url = admin.url(request, f"/{view.identity}/")
        targets.append(NavItem(view.name_plural, url, view.icon, request.url.path.startswith(url)))
    return targets
