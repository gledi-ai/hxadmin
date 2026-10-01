from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Post, Vote, allow_all
from tests.test_create_edit import build
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]


def test_delete_redirects_to_list(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/vote/2;1/delete", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/vote/"
        assert client.get("/admin/vote/2;1").status_code == 404
        listing = client.get("/admin/vote/").text
    assert "No votes yet" in listing


def test_delete_post_with_tags(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        client.post("/admin/vote/2;1/delete", follow_redirects=False)
        response = client.post("/admin/post/1/delete", follow_redirects=False)
        assert response.status_code == 303
        assert client.get("/admin/post/1").status_code == 404
        tags = client.get("/admin/tag/1").text
    assert "Tag" in tags


def test_delete_referenced_row_is_409(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        full = client.post("/admin/user/1/delete")
        partial = client.post("/admin/user/1/delete", headers={"HX-Request": "true"})
        detail = client.get("/admin/user/1")
    assert full.status_code == 409
    assert "409" in full.text
    assert "<html" in full.text
    assert partial.status_code == 409
    assert detail.status_code == 200
    assert "ada@x.io" in detail.text


def test_delete_htmx_sends_hx_redirect(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/vote/2;1/delete", headers={"HX-Request": "true"}, follow_redirects=False
        )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/admin/vote/"


def test_delete_not_found(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        assert client.post("/admin/post/999/delete").status_code == 404


def test_delete_can_delete_false_403(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        can_delete = False

    with make_client(app) as client:
        assert client.post("/admin/post/1/delete").status_code == 403
        listing = client.get("/admin/post/").text
        detail = client.get("/admin/post/1").text
    assert "/admin/post/1/delete" not in listing
    assert "/admin/post/1/delete" not in detail


def test_on_delete_hook_runs(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    deleted: list[str] = []

    @admin.register
    class VoteView(ModelView[Vote]):
        model = Vote

        async def on_delete(self, request: Request, session: AsyncSession, obj: Vote) -> None:
            deleted.append(self.pk_of(obj))

    with make_client(app) as client:
        client.post("/admin/vote/2;1/delete", follow_redirects=False)
    assert deleted == ["2;1"]


def test_delete_button_dispatches_confirm(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        detail = client.get("/admin/post/1").text
        listing = client.get("/admin/post/").text
    assert "$dispatch(&#39;confirm&#39;," in detail
    assert "&#34;danger&#34;: true" in detail
    assert "This cannot be undone." in detail
    assert "&#34;title&#34;: &#34;Delete post?&#34;" in detail
    assert "/admin/post/1/delete" in detail
    assert "/admin/post/1/delete" in listing
    assert 'href="/admin/post/1/edit"' in listing
    assert "@confirm.window" in detail


def test_delete_returns_to_the_list_as_shown(factory: AppFactory, make_client: MakeClient) -> None:
    shown = "http://testserver/admin/vote/?f.value.min=2&sort=value&page=1"
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/vote/2;1/delete", headers={"Referer": shown}, follow_redirects=False
        )
    assert response.headers["location"] == "/admin/vote/?f.value.min=2&sort=value&page=1"
