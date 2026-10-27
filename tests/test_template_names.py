from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin, ModelView, Page
from tests.conftest import AppFactory, User, allow_all

type MakeClient = Callable[[FastAPI], TestClient]


def _admin(factory: AppFactory, templates_dir: Path) -> tuple[FastAPI, HxAdmin]:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all, templates_dir=templates_dir)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    return app, admin


def test_a_page_template_named_like_a_builtin_does_not_replace_it(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    (tmp_path / "list.html").write_text(
        '{% extends "hxadmin/page.html" %}{% block body %}MY LIST PAGE{% endblock %}'
    )
    app, admin = _admin(factory, tmp_path)

    @admin.page("/mine", title="Mine")
    async def mine() -> Page:
        return Page("list.html")

    with make_client(app) as client:
        assert "MY LIST PAGE" not in client.get("/admin/user/").text
        assert "MY LIST PAGE" in client.get("/admin/mine").text


def test_builtins_are_overridden_under_the_hxadmin_folder(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    (tmp_path / "hxadmin").mkdir()
    (tmp_path / "hxadmin" / "dashboard.html").write_text(
        '{% extends "hxadmin/layout.html" %}{% block content %}CUSTOM DASH{% endblock %}'
    )
    app, _ = _admin(factory, tmp_path)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert "CUSTOM DASH" in html
    assert "<aside" in html


def test_an_override_can_extend_the_builtin_it_replaces(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    (tmp_path / "hxadmin").mkdir()
    (tmp_path / "hxadmin" / "dashboard.html").write_text(
        '{% extends "hxadmin-builtin/dashboard.html" %}'
        "{% block content %}<p>BANNER</p>{{ super() }}{% endblock %}"
    )
    app, _ = _admin(factory, tmp_path)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert "<p>BANNER</p>" in html
    assert html.index("<p>BANNER</p>") < html.index(">Dashboard</h1>")


def test_builtin_names_cannot_be_shadowed(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    (tmp_path / "hxadmin-builtin").mkdir()
    (tmp_path / "hxadmin-builtin" / "dashboard.html").write_text("SHADOWED")
    (tmp_path / "hxadmin").mkdir()
    (tmp_path / "hxadmin" / "dashboard.html").write_text(
        '{% extends "hxadmin-builtin/dashboard.html" %}'
    )
    app, _ = _admin(factory, tmp_path)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert "SHADOWED" not in html
    assert "<aside" in html
