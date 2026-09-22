from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.conftest import AppFactory
from tests.test_action_routes import HX, UserView, build, is_active, toast_of

type MakeClient = Callable[[FastAPI], TestClient]


class LockedUserView(UserView):
    def is_action_allowed(self, request: Request, name: str) -> bool:
        return name not in {"activate", "deactivate"}


def test_disallowed_actions_answer_403(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory, LockedUserView)) as client:
        row = client.post("/admin/user/2/action/activate", headers=HX)
        bulk = client.post("/admin/user/action/deactivate", data={"pks": ["1"]}, headers=HX)
        native = client.post("/admin/user/2/action/activate", follow_redirects=False)
        allowed = client.get("/admin/user/2/action/download")
        still_inactive = not is_active(client, 2)
    assert row.status_code == 403
    assert row.headers["HX-Reswap"] == "none"
    assert toast_of(row)["level"] == "error"
    assert bulk.status_code == 403
    assert native.status_code == 403
    assert allowed.status_code == 200
    assert still_inactive


def test_disallowed_actions_are_not_rendered(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory, LockedUserView)) as client:
        detail = client.get("/admin/user/2").text
        listing = client.get("/admin/user/").text
    assert "/action/activate" not in detail
    assert "/action/download" in detail
    assert "/action/activate" not in listing
    assert "/admin/user/action/deactivate" not in listing
    assert "/admin/user/action/export" in listing


def test_all_bulk_actions_disallowed_hides_selection(
    factory: AppFactory, make_client: MakeClient
) -> None:
    class NoBulkUserView(UserView):
        def is_action_allowed(self, request: Request, name: str) -> bool:
            return name not in {"deactivate", "export"}

    with make_client(build(factory, NoBulkUserView)) as client:
        listing = client.get("/admin/user/").text
    assert 'id="bulk"' not in listing
    assert 'name="pks"' not in listing
