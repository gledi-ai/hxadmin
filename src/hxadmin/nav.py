from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin


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
