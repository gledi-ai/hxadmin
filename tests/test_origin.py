import json
import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from hxadmin import HxAdmin
from hxadmin.origin import is_cross_origin, normalize_origin
from tests.conftest import AppFactory, allow_all
from tests.test_create_edit import build
from tests.test_detail import seed
from tests.test_pages import build as build_pages

type MakeClient = Callable[[FastAPI], TestClient]

EVIL = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}


def _request(method: str, headers: dict[str, str]) -> Request:
    merged = {"Host": "admin.example", **headers}
    raw = [(k.lower().encode(), v.encode()) for k, v in merged.items()]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw})


@pytest.mark.parametrize(
    ("method", "headers", "blocked"),
    [
        ("GET", {"Sec-Fetch-Site": "cross-site"}, False),
        ("HEAD", {"Origin": "https://evil.example"}, False),
        ("POST", {}, False),
        ("POST", {"Sec-Fetch-Site": "same-origin"}, False),
        ("POST", {"Sec-Fetch-Site": "none"}, False),
        ("POST", {"Sec-Fetch-Site": "same-site"}, True),
        ("POST", {"Sec-Fetch-Site": "cross-site"}, True),
        ("POST", {"Sec-Fetch-Site": "cross-site", "Origin": "https://admin.example"}, True),
        ("POST", {"Origin": "https://admin.example"}, False),
        ("POST", {"Origin": "http://ADMIN.example"}, False),
        ("POST", {"Origin": "https://admin.example:8443"}, True),
        ("POST", {"Origin": "https://evil.example"}, True),
        ("POST", {"Origin": "null"}, True),
        ("DELETE", {"Origin": "https://evil.example"}, True),
        ("PUT", {"Sec-Fetch-Site": "cross-site"}, True),
        ("PATCH", {"Sec-Fetch-Site": "cross-site"}, True),
    ],
)
def test_is_cross_origin(method: str, headers: dict[str, str], blocked: bool) -> None:
    assert is_cross_origin(_request(method, headers)) is blocked


def test_trusted_origins_pass_even_cross_site() -> None:
    trusted = {normalize_origin("https://ops.example")}
    ops = _request("POST", {"Origin": "https://ops.example", "Sec-Fetch-Site": "cross-site"})
    other = _request("POST", {"Origin": "https://other.example", "Sec-Fetch-Site": "same-site"})
    assert not is_cross_origin(ops, trusted)
    assert is_cross_origin(other, trusted)


@pytest.mark.parametrize(
    ("origin", "normalized"),
    [
        ("https://Ops.Example", "https://ops.example"),
        ("http://localhost:5173/", "http://localhost:5173"),
        (" https://ops.example ", "https://ops.example"),
    ],
)
def test_normalize_origin(origin: str, normalized: str) -> None:
    assert normalize_origin(origin) == normalized


@pytest.mark.parametrize(
    "origin",
    [
        "ops.example",
        "ftp://ops.example",
        "https://",
        "https://ops.example/admin",
        "https://ops.example?x=1",
        "https://user@ops.example",
        "*",
    ],
)
def test_invalid_trusted_origins_are_rejected(factory: AppFactory, origin: str) -> None:
    with pytest.raises(ValueError, match="Trusted origin"):
        HxAdmin(
            factory.app(), session=factory.get_session, auth=allow_all, trusted_origins=[origin]
        )


def test_cross_site_writes_are_blocked_and_change_nothing(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        created = client.post("/admin/group/new", data={"name": "Evil"}, headers=EVIL)
        edited = client.post("/admin/group/1/edit", data={"name": "Evil"}, headers=EVIL)
        deleted = client.post("/admin/vote/2;1/delete", headers=EVIL)
        groups = client.get("/admin/group/").text
        vote = client.get("/admin/vote/2;1")
    for response in (created, edited, deleted):
        assert response.status_code == 403
        assert "Cross-origin request blocked." in response.text
        assert "<html" in response.text
    assert "Evil" not in groups
    assert vote.status_code == 200


def test_same_origin_writes_pass(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        browser = client.post(
            "/admin/group/new",
            data={"name": "Browser"},
            headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            follow_redirects=False,
        )
        legacy = client.post(
            "/admin/group/new",
            data={"name": "Legacy"},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        groups = client.get("/admin/group/").text
    assert browser.status_code == 303
    assert legacy.status_code == 303
    assert "Browser" in groups
    assert "Legacy" in groups


def test_cross_site_reads_pass(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        assert client.get("/admin/group/", headers=EVIL).status_code == 200


def test_blocked_htmx_request_gets_an_error_toast(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/vote/2;1/delete", headers={**EVIL, "HX-Request": "true"})
    assert response.status_code == 403
    assert response.headers["HX-Reswap"] == "none"
    toast = json.loads(response.headers["HX-Trigger"])["hxadmin-toast"]
    assert toast["message"] == "Cross-origin request blocked."
    assert toast["level"] == "error"


def test_custom_page_writes_are_blocked(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    app, _ = build_pages(factory, tmp_path)
    with make_client(app) as client:
        blocked = client.post("/admin/sync/run", headers=EVIL, follow_redirects=False)
        allowed = client.post("/admin/sync/run", follow_redirects=False)
    assert blocked.status_code == 403
    assert allowed.status_code == 303


def test_trusted_origin_may_write(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    HxAdmin(
        app,
        session=factory.get_session,
        auth=allow_all,
        trusted_origins=["https://ops.example"],
    )
    with make_client(app) as client:
        trusted = client.post(
            "/admin/missing/new",
            headers={"Origin": "https://ops.example", "Sec-Fetch-Site": "cross-site"},
        )
        other = client.post("/admin/missing/new", headers=EVIL)
    assert trusted.status_code == 404
    assert other.status_code == 403


def test_blocked_requests_are_logged(
    factory: AppFactory, make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="hxadmin"), make_client(build(factory)) as client:
        client.post("/admin/vote/2;1/delete", headers=EVIL)
    assert any(
        "Blocked cross-origin POST /admin/vote/2;1/delete" in r.getMessage()
        and "https://evil.example" in r.getMessage()
        for r in caplog.records
    )
