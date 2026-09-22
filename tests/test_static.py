from collections.abc import Callable

from fastapi import FastAPI
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
    assert css.status_code == 200
    assert "--color-surface" in css.text
    assert ".dark" in css.text
    assert htmx.status_code == 200
    assert alpine.status_code == 200


def test_static_is_not_auth_guarded(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    from fastapi import HTTPException

    def deny() -> None:
        raise HTTPException(status_code=401)

    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")
    with make_client(app) as client:
        assert client.get("/admin/static/hxadmin.css").status_code == 200
