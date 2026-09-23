from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, User, allow_all

type MakeClient = Callable[[FastAPI], TestClient]


def test_sidebar_rail_toggle_markup(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    with make_client(app) as client:
        html = client.get("/admin/").text
    assert "lg:collapsed:w-14" in html
    assert "hxadmin-sidebar" in html
    assert "localStorage.getItem('hxadmin-sidebar')" in html
    assert "document.documentElement.classList.toggle('hxadmin-collapsed'" in html
    assert 'aria-label="Toggle sidebar"' in html
    assert "Toggle sidebar ⌘B" in html
    assert ".key.toLowerCase() === 'b'" in html
    assert "Collapse<" not in html
    assert 'class="hidden shrink-0 border-t border-border p-2 lg:block"' not in html


def test_nav_groups_have_aria_expanded(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group
        category = "Auth"

    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'aria-expanded="false" :aria-expanded="open"' in html
    assert ">Auth</span>" in html


def test_logo_url_rendered(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all, logo_url="/static/logo.svg")
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert '<img src="/static/logo.svg"' in html


def test_no_logo_url_falls_back_to_letter_tile(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert "<img" not in html
    assert 'bg-accent text-xs font-semibold text-accent-fg">H</span>' in html


def test_user_menu_shows_logout_when_set(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all, logout_url="/admin/logout")
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'href="/admin/logout"' in html
    assert ">Log out<" in html


def test_user_menu_hides_logout_without_logout_url(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert ">Log out<" not in html


def test_theme_radio_items(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'role="menuitemradio"' in html
    for label, mode in (("Light", "light"), ("Dark", "dark"), ("System", "system")):
        assert f"set(&#39;{mode}&#39;)" in html
        assert f"mode === &#39;{mode}&#39;" in html
        assert f">{label}<" in html


def test_no_old_global_search_form(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        searchable = ("email",)

    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'id="global-search"' not in html
    assert "search_targets" not in html


def test_htmx_settle_is_disabled_before_alpine_boots(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    with make_client(app) as client:
        html = client.get("/admin/").text
    setting = html.index("htmx.config.defaultSettleDelay = 0;")
    assert html.index("vendor/htmx.min.js") < setting < html.index('addEventListener("alpine:init"')


def test_scripts_listen_for_htmx_4_event_names(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    with make_client(app) as client:
        html = client.get("/admin/").text
    for legacy in ("htmx:afterSwap", "htmx:beforeCleanupElement", "htmx:afterSettle"):
        assert legacy not in html
    assert 'this.$refs.input.addEventListener("htmx:after:swap"' in html
    assert 'document.addEventListener("htmx:after:swap"' in html


def test_mobile_drawer_has_a_close_button_instead_of_the_rail_toggle(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    with make_client(app) as client:
        html = client.get("/admin/").text
    toggle = html[: html.index('aria-label="Toggle sidebar"')]
    assert "shrink-0 max-lg:hidden" in toggle[toggle.rindex("<button") :]
    close = html[: html.index('aria-label="Close navigation"')]
    assert "shrink-0 lg:hidden" in close[close.rindex("<button") :]


def test_theme_and_logout_render_without_a_user(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=lambda: None, logout_url="/logout")
    with make_client(app) as client:
        html = client.get("/admin/").text
    assert 'aria-label="Account menu"' in html
    assert html.count('role="menuitemradio"') == 3
    assert ">Log out<" in html
    assert "<span data-avatar" in html


def test_rail_mode_shows_the_items_of_closed_groups(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group
        category = "Auth"

    with make_client(app) as client:
        html = client.get("/admin/").text
    group = html[html.index('data-nav-group="Auth"') :]
    ul = group[group.index("<ul") : group.index(">", group.index("<ul"))]
    assert 'x-show="open"' in ul
    assert "lg:collapsed:block!" in ul


def test_closed_nav_groups_are_hidden_before_alpine_starts(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app()
    HxAdmin(app, session=factory.get_session, auth=allow_all)
    with make_client(app) as client:
        html = client.get("/admin/").text
    head = html[: html.index("vendor/htmx.min.js")]
    assert "[data-nav-group=\"' + CSS.escape(key.slice(14))" in head
    assert 'addEventListener("alpine:initialized"' in head
