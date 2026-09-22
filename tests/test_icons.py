from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin, ModelView, Page
from hxadmin.icons import icon
from tests.conftest import AppFactory, User, allow_all


def test_icon_inlines_the_lucide_svg() -> None:
    svg = str(icon("house", "size-6 text-fg-muted"))
    assert svg.startswith("<svg ")
    assert 'class="size-6 text-fg-muted"' in svg
    assert 'aria-hidden="true"' in svg
    assert 'stroke="currentColor"' in svg
    assert "<path" in svg
    assert "<!--" not in svg
    assert "lucide-house" not in svg


def test_icon_escapes_the_class() -> None:
    assert 'class="a&#34; onload=&#34;x"' in str(icon("x", 'a" onload="x'))


def test_icon_rejects_unknown_and_unsafe_names() -> None:
    with pytest.raises(ValueError, match="nope"):
        icon("nope")
    with pytest.raises(ValueError, match="LICENSE"):
        icon("../LICENSE")


def test_icon_macro_renders_svg_with_class(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    template = admin.templates.from_string(
        '{% import "_macros.html" as m %}{{ m.icon("plus") }}|{{ m.icon("x", "size-3") }}'
    )
    default, sized = template.render().split("|")
    assert default.startswith("<svg ")
    assert 'class="size-4"' in default
    assert 'class="size-3"' in sized


def test_nav_renders_view_icon(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        icon = "users"

    with make_client(app) as client:
        html = client.get("/admin/").text
    assert str(icon("users", "size-4 text-fg-muted")) in html


def test_unknown_view_icon_is_rejected_at_registration(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    class UserView(ModelView[User]):
        model = User
        icon = "not-an-icon"

    with pytest.raises(ValueError, match="not-an-icon"):
        admin.register(UserView)
    assert admin.views == {}


def test_unknown_page_icon_is_rejected_at_registration(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    with pytest.raises(ValueError, match="chart"):
        admin.page("/stats", title="Statistics", icon="chart")
    assert admin.pages == []


def test_lucide_page_icon_is_accepted(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.page("/stats", title="Statistics", icon="chart-column")
    async def stats() -> Page:
        return Page("page.html")

    assert admin.pages[0].icon == "chart-column"
