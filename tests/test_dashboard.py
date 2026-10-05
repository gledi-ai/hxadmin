import logging
import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, event, select
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

        def get_query(self, request: Request) -> Select[User]:
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
        rf'<a href="{re.escape(url)}" class="[^"]*rounded-lg.*?tabular-nums">(\d+)</div>',
        html,
        re.S,
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
    assert '<h2 class="mb-3 text-sm font-medium text-fg-muted">Auth</h2>' in main


def test_empty_dashboard(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        assert "No models registered." in client.get("/admin/").text


def test_no_global_search_form(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        home = client.get("/admin/").text
        posts = client.get("/admin/post/").text
    assert 'id="global-search"' not in home
    assert 'id="global-search"' not in posts


def test_dashboard_counts_all_views_in_one_query(
    factory: AppFactory, make_client: MakeClient
) -> None:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    app = build(factory)
    with make_client(app) as client:
        event.listen(factory.engine.sync_engine, "before_cursor_execute", record)
        try:
            html = client.get("/admin/").text
        finally:
            event.remove(factory.engine.sync_engine, "before_cursor_execute", record)
    assert card_count(html, "/admin/user/") == "2"
    assert card_count(html, "/admin/post/") == "1"
    assert len([s for s in statements if "count(" in s.lower()]) == 1


def test_broken_view_does_not_break_the_dashboard(
    factory: AppFactory, make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    @admin.register
    class Broken(ModelView[Post]):
        model = Post

        def get_query(self, request: Request) -> Select[Post]:
            raise RuntimeError("no")

    with caplog.at_level(logging.ERROR, logger="hxadmin"), make_client(app) as client:
        response = client.get("/admin/")
    assert response.status_code == 200
    assert card_count(response.text, "/admin/user/") == "2"
    assert re.search(r'href="/admin/post/".*?tabular-nums">—</div>', response.text, re.S)
    assert "Broken" in caplog.text


def test_single_model_categories_join_the_unheaded_grid(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        category = "People"

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        category = "Content"

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group
        category = "Content"

    with make_client(app) as client:
        main = client.get("/admin/").text.split('<main id="main"', 1)[1].split("</main>")[0]
    assert re.findall(r"<h2[^>]*>([^<]+)</h2>", main) == ["Content"]
    assert re.findall(r"data-card-category>([^<]+)<", main) == ["People"]
    assert main.index("/admin/user/") < main.index("<h2")


def test_fold_single_categories() -> None:
    from hxadmin.nav import DashboardCard, DashboardGroup, fold_single_categories

    def card(label: str) -> DashboardCard:
        return DashboardCard(label, f"/{label}", None, 1)

    groups = fold_single_categories(
        {None: [card("Posts")], "People": [card("Groups"), card("Users")], "Work": [card("Tags")]}
    )
    assert groups == [
        DashboardGroup(None, (card("Posts"), DashboardCard("Tags", "/Tags", None, 1, "Work"))),
        DashboardGroup("People", (card("Groups"), card("Users"))),
    ]
    assert fold_single_categories({None: [], "Work": [card("Tags"), card("Posts")]}) == [
        DashboardGroup("Work", (card("Tags"), card("Posts"))),
    ]
