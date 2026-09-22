from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, User, allow_all


def test_dashboard_renders_title(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all, title="Equalizer")
    with make_client(app) as client:
        response = client.get("/admin/")
    assert response.status_code == 200
    assert "<title>Equalizer</title>" in response.text


def test_custom_prefix(factory: AppFactory, make_client: Callable[[FastAPI], TestClient]) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all, prefix="/backoffice")
    with make_client(app) as client:
        assert client.get("/backoffice/").status_code == 200
        assert client.get("/admin/").status_code == 404


def test_register_returns_class_and_stores_instance(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    assert admin.views["user"].__class__ is UserView
    assert UserView.identity == "user"


def test_duplicate_identity_rejected(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.register
    class A(ModelView[User]):
        model = User

    with pytest.raises(ValueError, match="user"):

        @admin.register
        class B(ModelView[User]):
            model = User


def test_dashboard_lists_registered_views(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        name_plural = "People"

    with make_client(app) as client:
        response = client.get("/admin/")
    assert "People" in response.text
    assert 'href="/admin/user/"' in response.text
