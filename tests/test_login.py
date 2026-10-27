from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import HTMLResponse

from hxadmin import HxAdmin
from tests.conftest import AppFactory, allow_all
from tests.html import classes, tag

type MakeClient = Callable[[FastAPI], TestClient]


def _app(factory: AppFactory, **kwargs: Any) -> tuple[FastAPI, HxAdmin]:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all, title="Shop admin", **kwargs)
    return app, admin


def test_login_page_is_a_standalone_form(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _app(factory)

    @app.get("/login")
    async def login(request: Request) -> HTMLResponse:
        return admin.render_login(request)

    with make_client(app) as client:
        response = client.get("/login")
    html = response.text
    assert response.status_code == status.HTTP_200_OK
    assert 'href="/admin/static/hxadmin.css"' in html
    assert "<title>Sign in · Shop admin</title>" in html
    assert "<aside" not in html
    form = tag(html, "<form")
    assert 'method="post"' in form
    assert 'action="/login"' in form
    username = tag(html, 'name="username"')
    assert 'autocomplete="username"' in username
    assert "required" in username
    assert ">E-mail<" in html
    password = tag(html, 'name="password"')
    assert 'type="password"' in password
    assert 'autocomplete="current-password"' in password
    assert 'role="alert"' not in html
    assert 'localStorage.getItem("hxadmin-theme")' in html


def test_login_error_keeps_the_username(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _app(factory)

    @app.post("/sign-in")
    async def login(request: Request) -> HTMLResponse:
        return admin.render_login(
            request,
            error="Wrong e-mail or password.",
            username="ada@example.com",
            username_label="Username",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    with make_client(app) as client:
        response = client.post("/sign-in")
    html = response.text
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert 'action="/sign-in"' in tag(html, "<form")
    assert 'role="alert"' in html
    assert "Wrong e-mail or password." in html
    assert 'value="ada@example.com"' in tag(html, 'name="username"')
    assert ">Username<" in html
    assert "autofocus" in tag(html, 'name="password"')


def test_login_action_can_point_elsewhere(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _app(factory, prefix="/backoffice", logo_url="/logo.png")

    @app.get("/login")
    async def login(request: Request) -> HTMLResponse:
        return admin.render_login(request, action="/auth/login")

    with make_client(app) as client:
        html = client.get("/login").text
    assert 'action="/auth/login"' in tag(html, "<form")
    assert 'href="/backoffice/static/hxadmin.css"' in html
    assert 'src="/logo.png"' in html


def test_login_note_is_shown_under_the_form(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _app(factory)

    @app.get("/login")
    async def login(request: Request) -> HTMLResponse:
        return admin.render_login(request, note="Demo account: ada@example.com / demo")

    with make_client(app) as client:
        html = client.get("/login").text
    assert html.index("</form>") < html.index("Demo account: ada@example.com / demo")


def test_login_template_can_be_overridden(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    (tmp_path / "hxadmin").mkdir()
    (tmp_path / "hxadmin" / "login.html").write_text(
        "CUSTOM {{ action }} {{ error }} {{ admin.title }}"
    )
    app, admin = _app(factory, templates_dir=tmp_path)

    @app.get("/login")
    async def login(request: Request) -> HTMLResponse:
        return admin.render_login(request, error="Nope")

    with make_client(app) as client:
        html = client.get("/login").text
    assert html == "CUSTOM /login Nope Shop admin"


def test_login_button_is_full_width_primary(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _app(factory)

    @app.get("/login")
    async def login(request: Request) -> HTMLResponse:
        return admin.render_login(request)

    with make_client(app) as client:
        html = client.get("/login").text
    assert {"w-full", "bg-accent"} <= classes(tag(html, 'type="submit"'))
