from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from hxadmin import HxAdmin
from tests.conftest import AppFactory, allow_all


def test_static_assets_are_served(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        css = client.get("/admin/static/hxadmin.css")
        htmx = client.get("/admin/static/vendor/htmx.min.js")
        alpine = client.get("/admin/static/vendor/alpine.min.js")
        plugins = [
            client.get(f"/admin/static/vendor/alpine-{name}.min.js") for name in ("anchor", "focus")
        ]
    assert css.status_code == status.HTTP_200_OK
    assert "--color-surface" in css.text
    assert "--color-accent-soft" in css.text
    assert ".dark" in css.text
    assert htmx.status_code == status.HTTP_200_OK
    assert alpine.status_code == status.HTTP_200_OK
    assert [p.status_code for p in plugins] == [status.HTTP_200_OK] * 2


def test_static_is_not_auth_guarded(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    from fastapi import HTTPException

    def deny() -> None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")
    with make_client(app) as client:
        assert client.get("/admin/static/hxadmin.css").status_code == status.HTTP_200_OK


def test_checkboxes_are_drawn_with_theme_tokens() -> None:
    css = (Path(__file__).parent.parent / "src/hxadmin/static/hxadmin.css").read_text()
    assert "appearance:none" in css.replace(" ", "")
    assert "var(--hx-check-mark)" in css
    assert "var(--hx-dash-mark)" in css
    assert ":indeterminate" in css
