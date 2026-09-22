import json
from collections.abc import Callable
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response as HttpxResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from hxadmin import FormError, HxAdmin, ModelView
from hxadmin.toasts import FLASH_COOKIE
from tests.conftest import AppFactory, Post, User, allow_all
from tests.test_create_edit import POST_DATA, build
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]

EDIT_DATA = {"title": "Renamed", "status": "draft", "score": "0", "author": "1", "tags": ["1"]}


def flash_of(response: HttpxResponse) -> dict[str, str]:
    return json.loads(unquote(response.cookies[FLASH_COOKIE]))


def test_create_edit_and_delete_flash_a_success_toast(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        created = client.post("/admin/post/new", data=POST_DATA, follow_redirects=False)
        edited = client.post(
            "/admin/post/2/edit",
            data=EDIT_DATA,
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        deleted = client.post("/admin/vote/2;1/delete", follow_redirects=False)
    assert flash_of(created) == {"message": "Post “New” created.", "level": "success"}
    assert edited.headers["HX-Redirect"] == "/admin/post/2"
    assert flash_of(edited) == {"message": "Post “Renamed” saved.", "level": "success"}
    assert flash_of(deleted) == {"message": "Vote “Vote 2;1” deleted.", "level": "success"}


def test_toast_label_survives_expire_on_commit(
    factory: AppFactory, make_client: MakeClient
) -> None:
    factory.sessionmaker = async_sessionmaker(factory.engine, expire_on_commit=True)
    with make_client(build(factory)) as client:
        response = client.post("/admin/post/1/edit", data=EDIT_DATA, follow_redirects=False)
    assert flash_of(response)["message"] == "Post “Renamed” saved."


class GuardedPostView(ModelView[Post]):
    model = Post
    detail_columns = ("title", "body")

    async def on_save(
        self, request: Request, session: AsyncSession, obj: Post, *, created: bool
    ) -> None:
        obj.body = "touched"
        if obj.title == "bad":
            raise FormError("Titles cannot be 'bad'.", field="title")
        if obj.title == "worse":
            raise FormError("Not today.")
        if obj.title == "elsewhere":
            raise FormError("Nope.", field="missing")


class PlainUserView(ModelView[User]):
    model = User


def guarded(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(GuardedPostView)
    admin.register(PlainUserView)
    return app


def test_form_error_on_a_field_rerenders_the_form(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(guarded(factory)) as client:
        response = client.post("/admin/post/new", data={**POST_DATA, "title": "bad"})
        listing = client.get("/admin/post/").text
    assert response.status_code == 422
    assert (
        '<p class="mt-1 text-xs text-danger">Titles cannot be &#39;bad&#39;.</p>' in response.text
    )
    assert 'role="alert"' not in response.text
    assert 'value="bad"' in response.text
    assert "Showing 1\N{EN DASH}1 of 1" in listing


def test_form_error_without_a_known_field_is_form_level(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(guarded(factory)) as client:
        worse = client.post("/admin/post/1/edit", data={**EDIT_DATA, "title": "worse"})
        elsewhere = client.post(
            "/admin/post/1/edit",
            data={**EDIT_DATA, "title": "elsewhere"},
            headers={"HX-Request": "true"},
        )
        detail = client.get("/admin/post/1").text
    assert worse.status_code == 422
    assert 'role="alert"' in worse.text
    assert "Not today." in worse.text
    assert elsewhere.status_code == 422
    assert "<html" not in elsewhere.text
    assert "Nope." in elsewhere.text
    assert "Hello" in detail
    assert "touched" not in detail


class AuthoredPostView(ModelView[Post]):
    model = Post
    form_fields = ("title",)

    def display(self, obj: Post) -> str:
        return f"{obj.title} by {obj.author.email}"

    async def on_save(
        self, request: Request, session: AsyncSession, obj: Post, *, created: bool
    ) -> None:
        obj.author_id = 1


def test_toast_label_may_lazy_load(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(AuthoredPostView)
    with make_client(app) as client:
        created = client.post("/admin/post/new", data={"title": "New"}, follow_redirects=False)
        deleted = client.post("/admin/post/2/delete", follow_redirects=False)
    assert created.status_code == 303
    assert flash_of(created)["message"] == "Post “New by ada@x.io” created."
    assert deleted.status_code == 303
    assert flash_of(deleted)["message"] == "Post “New by ada@x.io” deleted."


class BlindPostView(ModelView[Post]):
    model = Post
    can_view = False


def test_save_without_detail_returns_to_the_list_as_shown(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(BlindPostView)
    admin.register(PlainUserView)
    shown = "http://testserver/admin/post/?f.status=draft&page=1"
    with make_client(app) as client:
        response = client.post(
            "/admin/post/new",
            data=POST_DATA,
            headers={"Referer": shown},
            follow_redirects=False,
        )
    assert response.headers["location"] == "/admin/post/?f.status=draft&page=1"
