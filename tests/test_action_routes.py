import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx2 import Response as HttpxResponse
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from hxadmin import ActionResult, HxAdmin, ModelView, action
from hxadmin.toasts import FLASH_COOKIE, TOAST_EVENT
from tests.conftest import AppFactory, User, allow_all
from tests.html import h1_texts
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]
HX = {"HX-Request": "true"}


async def seed_users(session: AsyncSession) -> None:
    await seed(session)
    session.add(User(email="cy@x.io", active=False))


class UserView(ModelView[User]):
    model = User
    list_columns = ("email", "active")
    searchable = ("email",)

    @action("deactivate", bulk=True, confirm="Deactivate selected users?")
    async def deactivate(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        for user in objs:
            user.active = False
        return ActionResult.message(f"Deactivated {len(objs)}")

    @action("export", bulk=True, method="GET", confirm="Export selected?")
    async def export(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        return ActionResult.response(PlainTextResponse(",".join(u.email for u in objs)))

    @action("activate")
    async def activate(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        obj.active = True
        return ActionResult.message(f"Activated {obj.email}")

    @action("download", method="GET")
    async def download(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.response(
            PlainTextResponse(obj.email, headers={"Content-Disposition": "attachment"})
        )

    @action("explode")
    async def explode(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        obj.active = False
        await session.flush()
        raise RuntimeError("boom")

    @action("forbid")
    async def forbid(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        obj.active = False
        raise HTTPException(status_code=403, detail="not you")

    @action("away")
    async def away(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.redirect("/elsewhere")

    @action("wrong")
    async def wrong(self, request: Request, session: AsyncSession, obj: User) -> Any:
        return "nope"

    @action("purge")
    async def purge(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        await session.delete(obj)
        return ActionResult.message("Purged")


def build(factory: AppFactory, view: type[ModelView[User]] = UserView) -> FastAPI:
    app = factory.app(seed=seed_users)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(view)
    return app


def toast_of(response: HttpxResponse) -> dict[str, str]:
    return json.loads(response.headers["HX-Trigger"])[TOAST_EVENT]


def is_active(client: TestClient, pk: int) -> bool:
    return 'aria-label="Yes"' in client.get(f"/admin/user/{pk}").text


def test_row_action_from_detail_rerenders_panel_with_toast(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/user/2/action/activate", data={"_from": "detail"}, headers=HX
        )
        active = is_active(client, 2)
    assert response.status_code == 200
    assert toast_of(response) == {
        "target": "body",
        "message": "Activated bob@x.io",
        "level": "success",
    }
    assert "<dl" in response.text
    assert "<html" not in response.text
    assert active


def test_row_action_from_list_rerenders_current_list(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/user/2/action/activate",
            data={"_from": "list"},
            headers={
                **HX,
                "HX-Current-URL": "http://testserver/admin/user/?q=bob&sort=email&dir=desc",
            },
        )
    assert response.status_code == 200
    assert 'id="list-state"' in response.text
    assert 'name="dir" value="desc"' in response.text
    assert "bob@x.io" in response.text
    assert "ada@x.io" not in response.text
    assert toast_of(response)["message"] == "Activated bob@x.io"


def test_row_action_without_htmx_redirects_with_flash(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/user/2/action/activate", follow_redirects=False)
        page = client.get("/admin/user/2")
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/user/2"
    assert FLASH_COOKIE in response.headers["set-cookie"]
    assert "Activated bob@x.io" in page.text


def test_bulk_action_updates_selected_rows(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/user/action/deactivate", data={"pks": ["1", "2", "2"]}, headers=HX
        )
        still_active = is_active(client, 1)
    assert response.status_code == 200
    assert toast_of(response)["message"] == "Deactivated 2"
    assert 'id="list-state"' in response.text
    assert not still_active


def test_bulk_action_is_scoped_by_get_query(factory: AppFactory, make_client: MakeClient) -> None:
    class Scoped(UserView):
        def get_query(self, request: Request) -> Select[tuple[User]]:
            return super().get_query(request).where(User.email != "ada@x.io")

    with make_client(build(factory, Scoped)) as client:
        response = client.post(
            "/admin/user/action/deactivate", data={"pks": ["1", "2"]}, headers=HX
        )
    assert toast_of(response)["message"] == "Deactivated 1"


@pytest.mark.parametrize("pks", [[], ["999"], ["not-a-pk"]])
def test_bulk_action_without_matching_rows_warns(
    factory: AppFactory, make_client: MakeClient, pks: list[str]
) -> None:
    with make_client(build(factory)) as client:
        hx = client.post("/admin/user/action/deactivate", data={"pks": pks}, headers=HX)
        native = client.post(
            "/admin/user/action/deactivate", data={"pks": pks}, follow_redirects=False
        )
    assert hx.status_code == 400
    assert hx.headers["HX-Reswap"] == "none"
    assert toast_of(hx) == {"target": "body", "message": "No rows selected.", "level": "warning"}
    assert native.status_code == 303
    assert native.headers["location"] == "/admin/user/"


def test_get_bulk_action_reads_query_string(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/user/action/export?pks=2&pks=1")
    assert response.status_code == 200
    assert response.text == "bob@x.io,ada@x.io"


def test_get_row_action_returns_raw_response(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/user/1/action/download")
    assert response.status_code == 200
    assert response.text == "ada@x.io"
    assert response.headers["content-disposition"] == "attachment"


def test_action_exception_rolls_back_and_toasts_error(
    factory: AppFactory, make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    with make_client(build(factory)) as client:
        with caplog.at_level(logging.ERROR, logger="hxadmin"):
            hx = client.post("/admin/user/1/action/explode", headers=HX)
        native = client.post("/admin/user/1/action/explode", follow_redirects=False)
        active = is_active(client, 1)
    assert hx.status_code == 500
    assert hx.headers["HX-Reswap"] == "none"
    assert toast_of(hx) == {"target": "body", "message": "Explode failed.", "level": "error"}
    assert "boom" not in hx.text
    assert any(
        r.exc_info is not None and isinstance(r.exc_info[1], RuntimeError) for r in caplog.records
    )
    assert native.status_code == 303
    assert native.headers["location"] == "/admin/user/1"
    assert active


def test_http_exception_in_action_propagates_after_rollback(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/user/1/action/forbid")
        active = is_active(client, 1)
    assert response.status_code == 403
    assert "not you" in response.text
    assert active


def test_non_action_result_is_an_error(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/user/1/action/wrong", headers=HX)
    assert response.status_code == 500
    assert toast_of(response)["message"] == "Wrong failed."


def test_redirect_result(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        hx = client.post("/admin/user/1/action/away", headers=HX)
        native = client.post("/admin/user/1/action/away", follow_redirects=False)
    assert hx.status_code == 200
    assert hx.headers["HX-Redirect"] == "/elsewhere"
    assert native.status_code == 303
    assert native.headers["location"] == "/elsewhere"


def test_row_action_that_deletes_its_object_redirects_to_list(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/user/3/action/purge", data={"_from": "detail"}, headers=HX)
        listing = client.get("/admin/user/")
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/admin/user/"
    assert "Purged" in listing.text
    assert "cy@x.io" not in listing.text


@pytest.mark.parametrize(
    ("method", "url", "status"),
    [
        ("POST", "/admin/user/1/action/nope", 404),
        ("POST", "/admin/user/action/nope", 404),
        ("POST", "/admin/user/1/action/deactivate", 404),
        ("POST", "/admin/user/action/activate", 404),
        ("GET", "/admin/user/1/action/activate", 405),
        ("POST", "/admin/user/1/action/download", 405),
        ("POST", "/admin/user/action/export", 405),
        ("POST", "/admin/user/999/action/activate", 404),
        ("POST", "/admin/nope/1/action/activate", 404),
    ],
)
def test_action_routing_errors(
    factory: AppFactory, make_client: MakeClient, method: str, url: str, status: int
) -> None:
    with make_client(build(factory)) as client:
        assert client.request(method, url).status_code == status


def test_inaccessible_view_rejects_actions(factory: AppFactory, make_client: MakeClient) -> None:
    class Locked(UserView):
        def is_accessible(self, request: Request) -> bool:
            return False

    with make_client(build(factory, Locked)) as client:
        assert client.post("/admin/user/2/action/activate").status_code == 403
        assert client.post("/admin/user/action/deactivate", data={"pks": ["1"]}).status_code == 403


def test_view_without_detail_rerenders_list(factory: AppFactory, make_client: MakeClient) -> None:
    class NoDetail(UserView):
        can_view = False

    with make_client(build(factory, NoDetail)) as client:
        response = client.post(
            "/admin/user/2/action/activate", data={"_from": "detail"}, headers=HX
        )
        native = client.post("/admin/user/2/action/activate", follow_redirects=False)
    assert 'id="list-state"' in response.text
    assert 'id="detail"' not in response.text
    assert native.headers["location"] == "/admin/user/"


def test_actions_follow_auth_redirect(factory: AppFactory, make_client: MakeClient) -> None:
    def deny() -> None:
        raise HTTPException(status_code=401)

    app = factory.app(seed=seed_users)
    admin = HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")
    admin.register(UserView)
    with make_client(app) as client:
        native = client.post("/admin/user/2/action/activate", follow_redirects=False)
        hx = client.post("/admin/user/action/deactivate", data={"pks": ["1"]}, headers=HX)
    assert native.status_code == 303
    assert native.headers["location"] == "/login"
    assert hx.headers["HX-Redirect"] == "/login"


def test_rerender_after_commit_with_expire_on_commit(
    factory: AppFactory, make_client: MakeClient
) -> None:
    factory.sessionmaker = async_sessionmaker(factory.engine, expire_on_commit=True)
    with make_client(build(factory)) as client:
        detail = client.post("/admin/user/2/action/activate", headers=HX)
        listing = client.post(
            "/admin/user/action/deactivate",
            data={"pks": ["1"]},
            headers={**HX, "HX-Current-URL": "http://testserver/admin/user/"},
        )
    assert detail.status_code == 200
    assert "<dl" in detail.text
    assert listing.status_code == 200
    assert "ada@x.io" in listing.text


def test_htmx_http_errors_toast_without_swapping_an_error_page(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        stale = client.post("/admin/user/99/action/activate", headers=HX)
        denied = client.post("/admin/user/1/action/forbid", headers=HX)
        native = client.post("/admin/user/99/action/activate")
    assert stale.status_code == 404
    assert stale.headers["HX-Reswap"] == "none"
    assert toast_of(stale)["level"] == "error"
    assert "<html" not in stale.text
    assert denied.status_code == 403
    assert denied.headers["HX-Reswap"] == "none"
    assert toast_of(denied)["message"] == "not you"
    assert native.status_code == 404
    assert "<html" in native.text


def test_handler_denial_does_not_redirect_to_login(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app(seed=seed_users)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all, login_url="/login")
    admin.register(UserView)
    with make_client(app) as client:
        htmx = client.post("/admin/user/1/action/forbid", headers=HX)
        native = client.post("/admin/user/1/action/forbid", follow_redirects=False)
    assert "HX-Redirect" not in htmx.headers
    assert htmx.status_code == 403
    assert toast_of(htmx)["message"] == "not you"
    assert native.status_code == 403
    assert "location" not in native.headers


def test_wrong_action_method_reports_allow(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/user/1/action/activate")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


class PingView(UserView):
    @action("ping", method="GET")
    async def ping(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.message("pong")


def test_native_list_actions_return_to_the_list_as_shown(
    factory: AppFactory, make_client: MakeClient
) -> None:
    shown = {"referer": "http://testserver/admin/user/?q=x.io&sort=email&dir=desc&page=1"}
    with make_client(build(factory, PingView)) as client:
        row = client.get(
            "/admin/user/1/action/ping?_from=list", headers=shown, follow_redirects=False
        )
        empty = client.get(
            "/admin/user/action/export?pks=99", headers=shown, follow_redirects=False
        )
        foreign = client.get(
            "/admin/user/1/action/ping?_from=list",
            headers={"referer": "http://evil.example/admin/user/?q=1"},
            follow_redirects=False,
        )
        other_page = client.get(
            "/admin/user/1/action/ping?_from=list",
            headers={"referer": "http://testserver/admin/group/?q=1"},
            follow_redirects=False,
        )
    assert row.headers["location"] == "/admin/user/?q=x.io&sort=email&dir=desc&page=1"
    assert empty.headers["location"] == "/admin/user/?q=x.io&sort=email&dir=desc&page=1"
    assert foreign.headers["location"] == "/admin/user/?q=1"
    assert other_page.headers["location"] == "/admin/user/"


class RenameView(UserView):
    @action("rename")
    async def rename(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        obj.email = "renamed@x.io"
        return ActionResult.message("Renamed")


def test_row_action_rerender_refreshes_the_detail_heading(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, RenameView)) as client:
        response = client.post("/admin/user/1/action/rename", headers=HX)
        full = client.get("/admin/user/1").text
    assert h1_texts(response.text) == ["renamed@x.io"]
    assert "/admin/user/1/action/rename" in response.text
    assert len(h1_texts(full)) == 1
