import re
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, Post, User, allow_all


async def seed(session: AsyncSession) -> None:
    staff = Group(name="staff")
    users = [User(email=f"user{i:02d}@x.io", active=i % 2 == 0, group=staff) for i in range(30)]
    session.add_all(users)
    session.add(Post(title="Hello", author=users[0]))


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class UserView(ModelView[User]):
        model = User
        list_columns = ("email", "active", "group")
        searchable = ("email",)
        default_sort = ("email", "asc")
        page_size = 10
        page_size_options = (10, 20)

        def format_email(self, obj: User) -> str:
            return obj.email.upper()

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        list_columns = ("title", "author", "tags")

        def get_query(self, request: Request) -> Select[tuple[Post]]:
            return super().get_query(request).where(Post.title != "Hidden")

    return app


def table_section(html: str) -> str:
    # The desktop table and the mobile card list render every row twice (one is
    # hidden per viewport via CSS); scope assertions to the table alone.
    return html[html.index("<table") :] if "<table" in html else html


def emails(html: str) -> list[str]:
    return re.findall(r"USER\d\d@X\.IO", table_section(html))


def test_full_page(factory: AppFactory, make_client: Callable[[FastAPI], TestClient]) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/").text
    assert "<html" in html
    assert "<title>Users" in html
    assert 'name="q"' in html
    assert emails(html) == [f"USER{i:02d}@X.IO" for i in range(10)]
    assert "Showing 1\u201310 of 30" in html
    assert 'href="/admin/user/1"' in html
    assert 'href="/admin/group/1"' not in html
    assert '<span class="text-fg-muted">Group 1</span>' in table_section(html)


def test_partial_on_hx_request(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/", headers={"HX-Request": "true"}).text
    assert "<html" not in html
    assert 'name="q"' not in html
    assert "<table" in html
    assert len(emails(html)) == 10


def test_search_sort_and_page(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        assert emails(client.get("/admin/user/?q=user2").text) == [
            f"USER{i}@X.IO" for i in range(20, 30)
        ]
        assert emails(client.get("/admin/user/?dir=desc&page=3").text) == [
            f"USER{i:02d}@X.IO" for i in range(9, -1, -1)
        ]
        html = client.get("/admin/user/?size=20&page=2").text
        assert len(emails(html)) == 10
        assert "Showing 21\u201330 of 30" in html


def test_sort_links_carry_state(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/?q=user&sort=email&dir=asc").text
    assert 'href="/admin/user/?q=user&amp;sort=email&amp;dir=desc&amp;page=1&amp;size=10"' in html
    assert 'href="/admin/user/?q=user&amp;sort=email&amp;dir=asc&amp;page=2&amp;size=10"' in html
    assert 'hx-target="closest .hx-list"' in html
    assert 'hx-push-url="true"' in html


def test_toolbar_state_survives_swap(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        full = client.get("/admin/user/?sort=email&dir=desc").text
        partial = client.get(
            "/admin/user/?sort=email&dir=desc", headers={"HX-Request": "true"}
        ).text
    assert 'hx-include="#list-state"' in full
    assert 'name="sort" value="email"' in partial
    assert 'name="dir" value="desc"' in partial
    assert 'name="size" value="10"' in partial


def test_empty_state(factory: AppFactory, make_client: Callable[[FastAPI], TestClient]) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/?q=nomatch").text
    assert "No users match these filters" in html
    assert "<tbody" not in html or emails(html) == []


def test_relation_cells(factory: AppFactory, make_client: Callable[[FastAPI], TestClient]) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    table = table_section(html)
    assert 'class="font-medium text-fg hover:underline">Hello</a>' in table
    assert '<span class="text-fg-muted">user00@x.io</span>' in table
    assert 'href="/admin/user/1"' not in table
    assert "<td" in html
    assert ">0</td>" in html


def test_bool_cells_use_icons(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/", headers={"HX-Request": "true"}).text
    table = table_section(html)
    assert table.count('aria-label="Yes"') == 5
    assert table.count('aria-label="No"') == 5


def test_get_query_override_filters_rows(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    async def seed_hidden(session: AsyncSession) -> None:
        await seed(session)
        session.add(Post(title="Hidden", author_id=1))

    app = factory.app(seed=seed_hidden)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

        def get_query(self, request: Request) -> Select[tuple[Post]]:
            return super().get_query(request).where(Post.title != "Hidden")

    with make_client(app) as client:
        html = client.get("/admin/post/").text
    assert "Hidden" not in html
    assert "Hello" in html


def test_unknown_identity_is_404(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        assert client.get("/admin/nope/").status_code == 404


def test_inaccessible_view_is_403(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

        def is_accessible(self, request: Request) -> bool:
            return False

    with make_client(app) as client:
        assert client.get("/admin/user/").status_code == 403


def test_no_detail_links_when_can_view_false(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        can_view = False

    with make_client(app) as client:
        html = client.get("/admin/user/").text
    assert 'href="/admin/user/1"' not in html


def test_only_the_primary_column_takes_the_remaining_width(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        table = table_section(client.get("/admin/user/").text)
    headers = re.findall(r'<th class="px-3 py-2 font-medium([^"]*)"', table)
    assert headers[0] == ""
    assert all(" w-px whitespace-nowrap" in extra for extra in headers[1:])
    assert "font-semibold" not in table[: table.index("</thead>")]


def test_header_shows_the_row_count_and_the_crumb_skips_the_title(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        full = client.get("/admin/user/").text
        partial = client.get("/admin/user/?q=user2", headers={"HX-Request": "true"}).text
    assert '<span id="list-count" class="font-normal tabular-nums text-fg-muted">30</span>' in full
    assert 'class="hover:underline">Dashboard</a></div>' in full
    assert (
        '<span id="list-count" hx-swap-oob="true" class="font-normal tabular-nums text-fg-muted">'
        "10</span>"
    ) in partial


def test_selected_rows_are_highlighted(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    from tests.test_action_ui import build as build_with_actions

    with make_client(build_with_actions(factory)) as client:
        html = client.get("/admin/user/").text
    assert '<tr class="hover:bg-surface-2 has-checked:bg-accent-soft/40">' in html
    assert "has-checked:border-accent/50 has-checked:bg-accent-soft/40" in html


def test_error_page_explains_the_status(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/nope/")
    assert response.status_code == 404
    assert ">Error 404</p>" in response.text
    assert '<h1 class="mt-1 text-2xl font-semibold">Not Found</h1>' in response.text
    assert "doesn&#39;t exist or has been moved." in response.text
