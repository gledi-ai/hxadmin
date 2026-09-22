from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin
from tests.conftest import AppFactory, allow_all


def test_theme_bootstrap_defaults_to_light(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'localStorage.getItem("hxadmin-theme") || "light"' in html
    assert 'classList.add("dark")' in html
    assert 'x-data="theme()"' in html


def test_templates_dir_overrides_package_templates(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient], tmp_path: Path
) -> None:
    (tmp_path / "dashboard.html").write_text(
        '{% extends "layout.html" %}{% block content %}CUSTOM DASH{% endblock %}'
    )
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all, templates_dir=tmp_path)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert "CUSTOM DASH" in html
    assert "<title>HxAdmin</title>" in html


def test_logout_url_rendered_when_set(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all, logout_url="/bye")
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'href="/bye"' in html


def test_alpine_plugins_load_before_alpine(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    anchor = html.index("/static/vendor/alpine-anchor.min.js")
    focus = html.index("/static/vendor/alpine-focus.min.js")
    assert anchor < html.index("/static/vendor/alpine.min.js")
    assert focus < html.index("/static/vendor/alpine.min.js")
