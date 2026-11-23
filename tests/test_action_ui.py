import re
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import ActionResult, HxAdmin, ModelView, action
from hxadmin.icons import icon
from tests.conftest import AppFactory, Group, User, allow_all
from tests.html import tag
from tests.test_action_routes import UserView, seed_users

type MakeClient = Callable[[FastAPI], TestClient]


class GroupView(ModelView[Group]):
    model = Group


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed_users)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(UserView)
    admin.register(GroupView)
    return app


def test_detail_renders_row_actions(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/2").text
    assert 'hx-post="/admin/user/2/action/activate"' in html
    assert 'hx-target="#detail"' in html
    assert 'hx-vals="{&#34;_from&#34;: &#34;detail&#34;}"' in html
    assert 'href="/admin/user/2/action/download"' in html
    download_icon = icon("download", "size-4 shrink-0 text-fg-muted")
    assert f'{download_icon}<span class="min-w-0 flex-1 truncate">Download</span>' in html
    assert "/admin/user/action/deactivate" not in html
    assert 'id="user-detail-actions"' in html


class PingUserView(ModelView[User]):
    model = User
    can_delete = False

    @action("ping")
    async def ping(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.message("pong")


def test_detail_inline_actions_render_as_buttons_not_menu_items(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app(seed=seed_users)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(PingUserView)
    with make_client(app) as client:
        html = client.get("/admin/user/2").text
    assert 'hx-post="/admin/user/2/action/ping"' in html
    assert f"{icon('zap', 'size-4 shrink-0')}Ping</button>" in html
    assert 'id="user-detail-actions"' not in html


def test_list_renders_selection_bulk_bar_and_row_actions(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/").text
        partial = client.get("/admin/user/", headers={"HX-Request": "true"}).text
    assert html.index('x-data="bulk()"') < html.index('id="list-filters"')
    assert '<form id="bulk"></form>' in html
    assert 'x-show="count > 0"' in tag(html, 'id="list-bulk-actions"')
    assert 'hx-post="/admin/user/action/deactivate"' in html
    assert f"{icon('zap', 'size-4 shrink-0')}Deactivate</button>" in html
    assert 'hx-target="#list"' in html
    assert 'hx-confirm="Deactivate selected users?"' in html
    assert 'formmethod="get" formaction="/admin/user/action/export"' in html
    assert f"{icon('download', 'size-4 shrink-0')}Export</button>" in html
    assert "requestSubmit($el)" in html
    assert "&#34;Export selected?&#34;" in html
    assert 'aria-label="Select all"' in html
    assert 'name="pks" value="1" form="bulk"' in html
    assert 'hx-post="/admin/user/1/action/activate"' in html
    assert 'hx-vals="{&#34;_from&#34;: &#34;list&#34;}"' in html
    assert 'href="/admin/user/1/action/download?_from=list"' in html
    assert 'hx-include="#list-state"' in html
    assert 'name="pks" value="1" form="bulk"' in partial
    assert '<form id="bulk"></form>' in partial
    assert 'hx-swap-oob="true"' in tag(partial, 'id="list-bulk-actions"')


def test_related_tables_and_views_without_actions_have_no_selection(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        related = client.get("/admin/group/_related/1/users").text
        groups = client.get("/admin/group/").text
    assert "ada@x.io" in related
    assert 'name="pks"' not in related
    assert "/action/" not in related
    assert 'name="pks"' not in groups
    assert 'id="bulk"' not in groups


def test_layout_bridges_htmx_confirm_into_the_modal(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/").text
    assert 'addEventListener("htmx:confirm"' in html
    assert "evt.detail.issueRequest" in html
    assert "evt.detail.dropRequest" in html
    assert 'id="confirm-dialog"' in html
    assert 'x-show="confirm"' in html
    assert 'Alpine.data("bulk"' in html
    assert "@confirm.window" in html


def test_row_controls_stay_visible_without_hover(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        listing = client.get("/admin/user/").text
    assert 'aria-label="Row actions"' in listing
    assert 'id="row-menu-1-trigger"' in listing


def test_row_menu_renders_default_icon_and_aligns_iconless_actions(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/").text
    default_item = re.search(
        r'<button type="button" role="menuitem"[^>]*'
        r'hx-post="/admin/user/1/action/activate"[^>]*>(.*?)</button>',
        html,
    )
    assert default_item is not None
    assert str(icon("zap", "size-4 shrink-0 text-fg-muted")) in default_item.group(1)
    iconless_item = re.search(
        r'<button type="button" role="menuitem"[^>]*'
        r'hx-post="/admin/user/1/action/explode"[^>]*>(.*?)</button>',
        html,
    )
    assert iconless_item is not None
    assert " pl-8 " in iconless_item.group(0)
    assert "<svg" not in iconless_item.group(1)


def test_select_all_is_a_valid_alpine_expression_and_tracks_partial_selection(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/").text
    start = html.index('data-select-all="desktop"')
    tag = html[start : html.index("</th>", start)]
    assert '@change="var ' not in tag
    assert ":indeterminate=" not in tag
    assert 'x-effect="$el.indeterminate = count > 0 && count < total;' in tag


def duplicate_ids(html: str) -> list[str]:
    ids = re.findall(r'\sid="([^"]+)"', html)
    return sorted({i for i in ids if ids.count(i) > 1})


def test_pages_have_no_duplicate_ids(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        pages = {
            url: client.get(url).text
            for url in ("/admin/", "/admin/user/", "/admin/user/2", "/admin/user/2/edit")
        }
    assert {url: duplicate_ids(html) for url, html in pages.items() if duplicate_ids(html)} == {}
    assert 'id="card-row-menu-1-trigger"' in pages["/admin/user/"]
