import re
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, select
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, Post, Tag, User, allow_all
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        category = "Auth"
        searchable = ("email",)

    @admin.register
    class ActiveUsers(ModelView[User]):
        model = User
        identity = "active-user"
        name_plural = "Active users"
        category = "Auth"

        def get_query(self, request: Request) -> Select[tuple[User]]:
            return select(User).where(User.active)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        searchable = ("title",)

    @admin.register
    class Hidden(ModelView[Tag]):
        model = Tag
        searchable = ("name",)

        def is_visible(self, request: Request) -> bool:
            return False

    @admin.register
    class Locked(ModelView[Group]):
        model = Group
        searchable = ("name",)

        def is_accessible(self, request: Request) -> bool:
            return False

    return app


def card_count(html: str, url: str) -> str | None:
    match = re.search(
        rf'<a href="{re.escape(url)}" class="rounded-lg.*?tabular-nums">(\d+)</div>', html, re.S
    )
    return match.group(1) if match else None


def test_dashboard_cards_show_row_counts(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/").text
    main = html.split('<main id="main"', 1)[1]
    assert card_count(main, "/admin/user/") == "2"
    assert card_count(main, "/admin/active-user/") == "1"
    assert card_count(main, "/admin/post/") == "1"
    assert card_count(main, "/admin/tag/") is None
    assert card_count(main, "/admin/group/") is None
    assert 'tracking-wide text-fg-muted">Auth</h2>' in main


def test_empty_dashboard(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        assert "No models registered." in client.get("/admin/").text


def test_global_search_targets_searchable_views(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        home = client.get("/admin/").text
        posts = client.get("/admin/post/").text
    assert '<form id="global-search" method="get" action="/admin/user/"' in home
    assert '<option value="/admin/user/"' in home
    assert '<option value="/admin/post/"' in home
    assert '<option value="/admin/active-user/"' not in home
    assert '<option value="/admin/tag/"' not in home
    assert '<option value="/admin/group/"' not in home
    assert '<form id="global-search" method="get" action="/admin/post/"' in posts


def test_no_global_search_without_searchable_views(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        assert 'id="global-search"' not in client.get("/admin/").text
