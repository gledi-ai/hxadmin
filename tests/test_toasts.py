import json
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from hxadmin import HxAdmin
from hxadmin.toasts import FLASH_COOKIE, TOAST_EVENT, Toast, encode_flash, hx_trigger, read_flash
from tests.conftest import AppFactory, allow_all

type MakeClient = Callable[[FastAPI], TestClient]


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin/",
            "root_path": "/admin",
            "headers": headers or [],
            "query_string": b"",
        }
    )


def _cookie_request(value: str) -> Request:
    return _request([(b"cookie", f"{FLASH_COOKIE}={value}".encode())])


def test_hx_trigger_payload_targets_body_and_is_ascii() -> None:
    value = hx_trigger(Toast('Café <b>"x"</b>', "error"))
    assert value.isascii()
    assert json.loads(value) == {
        TOAST_EVENT: {"target": "body", "message": 'Café <b>"x"</b>', "level": "error"}
    }


def test_flash_round_trip() -> None:
    toast = Toast('Done; 100% ✓ "ok"', "warning")
    assert read_flash(_cookie_request(encode_flash(toast))) == toast


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-json",
        "%5B1%5D",
        "%7B%22message%22%3A1%2C%22level%22%3A%22info%22%7D",
        encode_flash(Toast("x")).replace("success", "loud"),
    ],
)
def test_malformed_flash_is_ignored(value: str) -> None:
    assert read_flash(_cookie_request(value)) is None


def test_redirect_with_toast_sets_flash_cookie(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    native = admin.redirect(_request(), "/admin/user/", toast=Toast("Saved"))
    htmx = admin.redirect(
        _request([(b"hx-request", b"true")]), "/admin/user/", toast=Toast("Saved")
    )
    plain = admin.redirect(_request(), "/admin/user/")
    assert native.status_code == 303
    cookie = native.headers["set-cookie"]
    assert cookie.startswith(f"{FLASH_COOKIE}=")
    assert "Path=/admin/" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=60" in cookie
    assert htmx.status_code == 200
    assert htmx.headers["HX-Redirect"] == "/admin/user/"
    assert htmx.headers["set-cookie"].startswith(f"{FLASH_COOKIE}=")
    assert "set-cookie" not in plain.headers


def _flash_app(factory: AppFactory) -> FastAPI:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    async def flash(request: Request) -> Response:
        return admin.redirect(request, admin.url(request, "/"), toast=Toast("Saved <3"))

    admin.subapp.add_api_route("/_flash", flash)
    return app


def test_flash_toast_rendered_once_and_cleared(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(_flash_app(factory)) as client:
        first = client.get("/admin/_flash")
        second = client.get("/admin/")
    assert first.status_code == 200
    assert "Saved \\u003c3" in first.text
    assert "Saved <3" not in first.text
    assert "Max-Age=0" in first.headers["set-cookie"]
    assert "Saved" not in second.text
    assert 'x-data="toasts([])"' in second.text


def test_htmx_requests_do_not_consume_flash(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(_flash_app(factory)) as client:
        client.get("/admin/_flash", follow_redirects=False)
        partial = client.get("/admin/", headers={"HX-Request": "true"})
        full = client.get("/admin/")
    assert "set-cookie" not in partial.headers
    assert "Saved" not in partial.text
    assert "Saved \\u003c3" in full.text


def test_malformed_flash_cookie_still_renders_and_is_cleared(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        response = client.get("/admin/", headers={"cookie": f"{FLASH_COOKIE}=garbage"})
    assert response.status_code == 200
    assert 'x-data="toasts([])"' in response.text
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_layout_has_toast_container(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'id="toasts"' in html
    assert '@hxadmin-toast.window="push($event.detail)"' in html
    assert 'Alpine.data("toasts"' in html


@pytest.mark.parametrize("char", ["a", "é", "😀"])
def test_long_flash_is_truncated_to_fit_a_cookie(char: str) -> None:
    value = encode_flash(Toast(char * 5000, "info"))
    toast = read_flash(_cookie_request(value))
    assert len(value) < 4000
    assert toast is not None
    assert toast.level == "info"
    assert toast.message.startswith(char * 100)
    assert toast.message.endswith("…")
