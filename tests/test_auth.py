import re
from collections.abc import Callable

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from hxadmin import HxAdmin
from tests.conftest import AppFactory


def deny() -> None:
    raise HTTPException(status_code=401)


def forbid() -> None:
    raise HTTPException(status_code=403, detail="nope")


def test_unauthenticated_redirects_to_login(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")
    with make_client(app) as client:
        response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_htmx_request_gets_hx_redirect(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")
    with make_client(app) as client:
        response = client.get("/admin/", headers={"HX-Request": "true"}, follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/login"


def test_without_login_url_status_is_kept(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=forbid)
    with make_client(app) as client:
        response = client.get("/admin/")
    assert response.status_code == 403
    assert "nope" in response.text
    assert "<html" in response.text


def test_user_is_available_in_template(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    def who() -> dict[str, str]:
        return {"name": "gledi"}

    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=who)
    with make_client(app) as client:
        response = client.get("/admin/")
    assert "gledi" in response.text


class _EmailUser:
    email = "ada@example.com"

    def __str__(self) -> str:
        return self.email


class _NamedUser:
    def __init__(self, name: object) -> None:
        self.name = name

    def __str__(self) -> str:
        return "fallback"


@pytest.mark.parametrize(
    ("returned", "label", "initials"),
    [
        (True, None, None),
        ({"id": 1}, "{&#39;id&#39;: 1}", None),
        (_EmailUser(), "ada@example.com", "A"),
        (_NamedUser(None), "fallback", "F"),
        (_NamedUser("Grace Hopper"), "Grace Hopper", "GH"),
        (42, "42", "4"),
    ],
)
def test_any_auth_return_value_renders_the_user_menu(
    factory: AppFactory,
    make_client: Callable[[FastAPI], TestClient],
    returned: object,
    label: str | None,
    initials: str | None,
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=lambda: returned)
    with make_client(app) as client:
        response = client.get("/admin/")
    assert response.status_code == 200
    assert 'aria-label="Account menu"' in response.text
    if label is not None:
        assert f">{label}<" in response.text
    if initials is not None:
        assert re.search(rf"<span data-avatar[^>]*>{initials}</span>", response.text)
