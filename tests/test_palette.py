import types
from collections.abc import Callable
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, Post, Tag, User, allow_all
from tests.js import needs_node, run_layout_js
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]


def deny() -> None:
    raise HTTPException(status_code=401)


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        searchable = ("email",)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        searchable = ("title",)
        can_view = False

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class Hidden(ModelView[Tag]):
        model = Tag
        searchable = ("name",)

        def is_visible(self, request: Request) -> bool:
            return False

    @admin.register
    class Locked(ModelView[Group]):
        model = Group
        identity = "locked-group"
        name_plural = "Restricted"
        searchable = ("name",)

        def is_accessible(self, request: Request) -> bool:
            return False

    return app


def test_empty_query_lists_nav(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/_palette").text
    assert "Go to" in html
    assert ">Users<" in html
    assert ">Posts<" in html
    assert ">Groups<" in html
    assert ">Tags<" not in html
    assert ">Restricted<" not in html
    assert 'role="option"' in html
    assert 'role="group" aria-label="Go to"' in html


def test_query_filters_go_to(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/_palette", params={"q": "user"}).text
    assert ">Users<" in html
    assert ">Posts<" not in html
    assert ">Groups<" not in html


def test_record_hits_and_links(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/_palette", params={"q": "ada"}).text
    assert "ada@x.io" in html
    assert 'href="/admin/user/1"' in html


def test_record_link_falls_back_to_list_when_not_viewable(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/_palette", params={"q": "hello"}).text
    assert ">Hello<" in html
    assert f'href="/admin/post/?q={quote("hello")}"' in html


def test_inaccessible_views_excluded(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        hidden = client.get("/admin/_palette", params={"q": "news"}).text
        locked = client.get("/admin/_palette", params={"q": "staff"}).text
    assert 'role="group" aria-label="Tags"' not in hidden
    assert "news" not in hidden
    assert 'role="group" aria-label="Restricted"' not in locked
    assert "staff" not in locked


def test_view_without_searchable_is_skipped(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/_palette", params={"q": "staff"}).text
    assert 'role="group" aria-label="Groups"' not in html


def _register_many(admin: HxAdmin, count: int) -> None:
    for i in range(count):

        def _body(ns: dict[str, object], i: int = i) -> None:
            ns["model"] = User
            ns["identity"] = f"v{i}"
            ns["name_plural"] = f"V{i}"
            ns["searchable"] = ("email",)

        view_cls = types.new_class(f"View{i}", (ModelView[User],), exec_body=_body)
        admin.register(view_cls)


async def _many_users(session: AsyncSession) -> None:
    group = Group(name="staff")
    session.add_all([User(email=f"user{i}@x.io", group=group) for i in range(7)])


def test_per_view_hit_limit_is_five(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=_many_users)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        searchable = ("email",)

    with make_client(app) as client:
        html = client.get("/admin/_palette", params={"q": "x.io"}).text
    assert html.count('role="option"') == 5


def test_eight_view_limit(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    _register_many(admin, 9)

    with make_client(app) as client:
        html = client.get("/admin/_palette", params={"q": "x.io"}).text
    groups = [f'aria-label="V{i}"' in html for i in range(9)]
    assert sum(groups) == 8
    assert groups[8] is False


def test_palette_requires_auth(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")
    with make_client(app) as client:
        response = client.get("/admin/_palette", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_palette_loads_results_on_open_and_opens_near_the_top(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/").text
    assert 'hx-trigger="input changed delay:150ms, palette-open"' in html
    assert 'dispatchEvent(new CustomEvent("palette-open"))' in html
    panel = html[html.index('id="palette" role="dialog"') :]
    panel = panel[: panel.index(">")]
    assert "sm:mt-[12vh] sm:self-start" in panel


def test_palette_has_a_search_button_on_small_screens(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/").text
    button = html[: html.index('aria-label="Search or jump to"')]
    button = button[button.rindex("<") :]
    assert "sm:hidden" in button
    assert '@click="launch()"' in html[html.index('aria-label="Search or jump to"') :][:200]


@needs_node
def test_palette_sets_aria_activedescendant_when_highlighting(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/").text
    assert ':aria-activedescendant="' not in html
    probe = """
    const attrs = {};
    const opts = ["a", "b", "c"].map((id) => ({
      id, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, scrollIntoView() {},
    }));
    const p = factories.palette();
    p.$refs = {
      input: { setAttribute(k, v) { attrs[k] = v; } },
      results: { querySelectorAll: () => opts },
    };
    p.reset();
    const first = attrs["aria-activedescendant"];
    p.move(-1);
    const wrapped = attrs["aria-activedescendant"];
    console.log(JSON.stringify([first, wrapped, opts.map((o) => o.attrs["aria-selected"])]));
    """
    assert run_layout_js(html, probe) == ["a", "c", ["false", "false", "true"]]
