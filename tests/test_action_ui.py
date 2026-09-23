from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, allow_all
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
    assert "/admin/user/action/deactivate" not in html


def test_list_renders_selection_bulk_bar_and_row_actions(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/").text
        partial = client.get("/admin/user/", headers={"HX-Request": "true"}).text
    assert '<div id="list" class="hx-list" x-data="bulk()">' in html
    assert '<form id="bulk" x-show="count"' in html
    assert 'hx-post="/admin/user/action/deactivate"' in html
    assert 'hx-target="#list"' in html
    assert 'hx-confirm="Deactivate selected users?"' in html
    assert 'formmethod="get" formaction="/admin/user/action/export"' in html
    assert "requestSubmit($el)" in html
    assert "&#34;Export selected?&#34;" in html
    assert 'aria-label="Select all"' in html
    assert 'name="pks" value="1" form="bulk"' in html
    assert 'hx-post="/admin/user/1/action/activate"' in html
    assert 'hx-vals="{&#34;_from&#34;: &#34;list&#34;}"' in html
    assert 'href="/admin/user/1/action/download?_from=list"' in html
    assert 'hx-include="#list-state"' in html
    assert 'name="pks" value="1" form="bulk"' in partial
    assert '<form id="bulk"' in partial


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
    assert '@click.self="dismiss()"' in html
    assert 'Alpine.data("bulk"' in html
    assert "@confirm.window" in html


def test_row_controls_stay_visible_without_hover(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        listing = client.get("/admin/user/").text
    assert 'aria-label="Row actions"' in listing
    assert 'id="row-menu-1-trigger"' in listing
