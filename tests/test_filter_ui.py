from collections.abc import Callable, Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import ActionResult, HxAdmin, ModelView, action
from tests.conftest import AppFactory, Post, Tag, User, allow_all
from tests.test_filters import seed

type MakeClient = Callable[[FastAPI], TestClient]
HX = {"HX-Request": "true"}


class PostView(ModelView[Post]):
    model = Post
    list_columns = ("title", "status", "score", "author")
    list_filters = ("status", "score", "published_at", "title", "author")
    default_sort = ("title", "asc")

    @action("touch", bulk=True)
    async def touch(
        self, request: Request, session: AsyncSession, objs: Sequence[Post]
    ) -> ActionResult:
        return ActionResult.message(f"Touched {len(objs)}")


class UserView(ModelView[User]):
    model = User


class HiddenUserView(ModelView[User]):
    model = User

    def is_accessible(self, request: Request) -> bool:
        return False


class TagView(ModelView[Tag]):
    model = Tag


async def seed_tagged(session: AsyncSession) -> None:
    await seed(session)
    session.add(Tag(name="all", posts=list((await session.scalars(select(Post))).all())))


def build(factory: AppFactory, user_view: type[ModelView[User]] = UserView) -> FastAPI:
    app = factory.app(seed=seed_tagged)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(PostView)
    admin.register(user_view)
    admin.register(TagView)
    return app


def test_panel_reflects_the_current_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published&f.score.min=1&f.author=2").text
    assert 'id="list-filters"' in html
    assert 'x-data="{ open: true }"' in html
    assert 'name="f.status" value="published" checked' in html
    assert 'name="f.status" value="draft" class' in html
    assert 'name="f.score.min" value="1"' in html
    assert 'name="f.author" value="1" class="hx-filter-pick accent-accent"> ada@x.io' in html
    assert 'name="f.author" value="2" checked' in html
    assert 'name="f.published_at.empty"' in html
    assert 'name="f.status.empty"' not in html
    assert "Showing 1\N{EN DASH}1 of 1" in html


def test_panel_starts_closed_without_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
        users = client.get("/admin/user/").text
    assert 'x-data="{ open: false }"' in html
    assert 'id="filter-panel" x-show="open" x-cloak' in html
    assert 'id="filter-panel"' not in users
    assert "Filters</button>" not in users


def test_toolbar_submits_on_filter_changes(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    assert (
        'hx-trigger="input changed delay:300ms from:[name=q], input delay:300ms '
        'target:.hx-filter-text, change target:.hx-filter-pick, submit"'
    ) in html
    assert 'hx-include="#list-state"' in html
    assert "window.hxadminClearFilter = function (name, value)" in html
    assert '@click="hxadminClearFilter(null, null)"' in html


def test_partial_renders_chips_not_the_panel(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.author=2&f.title=a", headers=HX).text
    assert 'id="list-filters"' not in html
    assert 'aria-label="Remove filter Author: bob@x.io"' in html
    assert "hxadminClearFilter(&#34;f.author&#34;, &#34;2&#34;)" in html
    assert "hxadminClearFilter(&#34;f.title&#34;, null)" in html
    assert "Showing 1\N{EN DASH}2 of 2" in html


def test_sort_and_page_links_keep_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published", headers=HX).text
    assert '?f.status=published&amp;sort=title&amp;dir=desc&amp;page=1&amp;size=25"' in html
    assert 'hx-get="/admin/post/?f.status=published&amp;sort=title&amp;dir=asc&amp;page=1"' in html


def test_relation_filter_hidden_when_target_is_inaccessible(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, HiddenUserView)) as client:
        html = client.get("/admin/post/?f.author=2").text
    assert 'name="f.author"' not in html
    assert "Remove filter Author" not in html
    assert "Showing 1\N{EN DASH}3 of 3" in html


def test_action_rerender_keeps_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/post/action/touch",
            data={"pks": ["1"], "_from": "list"},
            headers={**HX, "HX-Current-URL": "http://testserver/admin/post/?f.status=published"},
        )
    assert response.status_code == 200
    assert "Showing 1\N{EN DASH}2 of 2" in response.text
    assert 'aria-label="Remove filter Status: published"' in response.text


def test_related_tab_ignores_filters_of_a_hidden_target(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, HiddenUserView)) as client:
        html = client.get("/admin/tag/_related/1/posts?f.author=1").text
    assert all(title in html for title in ("Alpha", "Beta", "Gamma 100%"))


def test_related_tab_reads_no_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/tag/_related/1/posts?f.status=draft").text
    assert "Showing 1\N{EN DASH}3 of 3" in html
