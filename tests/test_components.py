from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hxadmin import HxAdmin, Page
from hxadmin.components import html_attrs
from tests.conftest import AppFactory, allow_all

type MakeClient = Callable[[FastAPI], TestClient]
type Element = tuple[str, dict[str, str | None]]

CASES = {
    "primary": '{{ m.button("Save <now>", "primary", type="submit", hx_post="/x",'
    ' attrs={"@click": "go()"}) }}',
    "secondary": '{{ m.button("Cancel", size="sm", class="ml-auto") }}',
    "ghost": '{{ m.button("More", "ghost", icon="plus") }}',
    "danger": '{{ m.button("Delete", "danger", disabled=True) }}',
    "link": '{{ m.button("New", "primary", href="/new") }}',
    "dead-link": '{{ m.button("Next", href="/next", disabled=True) }}',
    "icon-button": '{{ m.icon_button("x", "Close", size="sm") }}',
    "icon-danger": '{{ m.icon_button("trash-2", "Delete", "danger", href="/d") }}',
    "badges": '{{ m.badge("draft") }}{{ m.badge("done", "success", icon="check") }}'
    '{{ m.badge("late", "danger") }}',
    "card": '{% call m.card("Details", "Shown to all") %}<p id="card-body">x</p>{% endcall %}',
    "link-card": '{% call m.card(href="/c", padded=False) %}<table></table>{% endcall %}',
    "menu": (
        '{% call m.menu("row-menu-1", m.icon("ellipsis"), label="Row actions",'
        ' trigger_class=m.button_classes("ghost", "sm", square=True), placement="bottom-end") %}'
        '{{ m.menu_label("Record") }}'
        '{{ m.menu_item("Edit", href="/e", icon="pencil", shortcut="E") }}'
        '{{ m.menu_item("Archive", disabled=True) }}'
        "{{ m.menu_separator() }}"
        '{{ m.menu_item("Delete", icon="trash-2", tone="danger", attrs={"@click": "del()"}) }}'
        "{% endcall %}"
    ),
    "popover": (
        '{% call m.popover("filter-status", "Status", size="sm") %}'
        '<input name="f.status">{% endcall %}'
    ),
    "dialog": (
        '{% call m.dialog("confirm", "Delete task?", "This cannot be undone.",'
        ' open="confirm", close="dismiss()", size="sm") %}{% call m.dialog_footer() %}'
        '{{ m.button("Cancel", autofocus=True) }}{{ m.button("Delete", "danger") }}'
        "{% endcall %}{% endcall %}"
    ),
    "plain-dialog": '{% call m.dialog("plain", "Hi", dismissible=False,'
    ' title_expr="t") %}{% endcall %}',
    "empty": '{{ m.empty_state("inbox", "No tasks yet", "Create one.",'
    ' action=m.button("New task", "primary", href="/n")) }}',
    "stat": '{{ m.stat("Open", 12, href="/s", icon="users", hint="3 today") }}'
    '{{ m.stat("Failed", none) }}',
    "alerts": '{{ m.alert("Could not save.", "danger", title="Error") }}'
    '{{ m.alert("Saved.", "success") }}',
    "tooltip": '{% call m.tooltip("Users", when="collapsed") %}<a href="/u">U</a>{% endcall %}',
    "kbd": '{{ m.kbd("⌘K") }}',
}


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.case: str | None = None
        self.depth = 0
        self.found: dict[str, list[Element]] = {}
        self.text: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "section" and values.get("data-case"):
            self.case = values["data-case"]
            self.found[self.case] = []
            self.text[self.case] = ""
            self.depth = 0
        elif self.case is not None:
            self.found[self.case].append((tag, values))
        if self.case is not None and tag == "section":
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.case is not None and tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.case = None

    def handle_data(self, data: str) -> None:
        if self.case is not None:
            self.text[self.case] += data


@pytest.fixture
def rendered(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> tuple[dict[str, list[Element]], dict[str, str], str]:
    body = "".join(f'<section data-case="{name}">{src}</section>' for name, src in CASES.items())
    (tmp_path / "components_demo.html").write_text(
        '{% extends "page.html" %}{% import "_macros.html" as m with context %}'
        "{% block body %}" + body + "{% endblock %}"
    )
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all, templates_dir=tmp_path)

    @admin.page("/components", title="Components")
    async def components() -> Page:
        return Page("components_demo.html")

    with make_client(app) as client:
        response = client.get("/admin/components")
    assert response.status_code == 200
    parser = _Collector()
    parser.feed(response.text)
    return parser.found, parser.text, response.text


def _classes(attrs: dict[str, str | None]) -> set[str]:
    return set((attrs.get("class") or "").split())


def _only(elements: list[Element], tag: str) -> list[dict[str, str | None]]:
    return [attrs for name, attrs in elements if name == tag]


def test_button_variants_sizes_and_extra_attributes(
    rendered: tuple[dict[str, list[Element]], dict[str, str], str],
) -> None:
    found, text, _ = rendered
    (primary,) = _only(found["primary"], "button")
    assert primary["type"] == "submit"
    assert {"bg-accent", "text-accent-fg", "h-9", "rounded-md"} <= _classes(primary)
    assert primary["hx-post"] == "/x"
    assert primary["@click"] == "go()"
    assert text["primary"] == "Save <now>"
    (secondary,) = _only(found["secondary"], "button")
    assert secondary["type"] == "button"
    assert {"border", "border-border", "bg-surface", "h-8", "ml-auto"} <= _classes(secondary)
    (ghost,) = _only(found["ghost"], "button")
    assert "hover:bg-surface-2" in _classes(ghost)
    assert _only(found["ghost"], "svg")[0]["aria-hidden"] == "true"
    (danger,) = _only(found["danger"], "button")
    assert {"bg-danger", "text-danger-fg"} <= _classes(danger)
    assert "disabled" in danger


def test_button_links(rendered: tuple[dict[str, list[Element]], dict[str, str], str]) -> None:
    found, _, _ = rendered
    (link,) = _only(found["link"], "a")
    assert link["href"] == "/new"
    assert "bg-accent" in _classes(link)
    (dead,) = _only(found["dead-link"], "a")
    assert "href" not in dead
    assert dead["aria-disabled"] == "true"


def test_icon_button_is_square_and_labelled(
    rendered: tuple[dict[str, list[Element]], dict[str, str], str],
) -> None:
    found, _, _ = rendered
    (button,) = _only(found["icon-button"], "button")
    assert button["aria-label"] == "Close"
    assert {"size-8", "text-fg-muted"} <= _classes(button)
    (link,) = _only(found["icon-danger"], "a")
    assert link["aria-label"] == "Delete"
    assert link["href"] == "/d"
    assert {"size-9", "text-danger", "hover:bg-danger-soft"} <= _classes(link)


def test_badge_tones(rendered: tuple[dict[str, list[Element]], dict[str, str], str]) -> None:
    found, text, _ = rendered
    neutral, success, danger = _only(found["badges"], "span")
    assert {"bg-surface-2", "text-fg", "text-xs"} <= _classes(neutral)
    assert {"bg-success-soft", "text-success"} <= _classes(success)
    assert {"bg-danger-soft", "text-danger"} <= _classes(danger)
    assert len(_only(found["badges"], "svg")) == 1
    assert text["badges"] == "draftdonelate"


def test_card_header_body_and_link(
    rendered: tuple[dict[str, list[Element]], dict[str, str], str],
) -> None:
    found, text, _ = rendered
    card = found["card"][0]
    assert card[0] == "div"
    assert {"rounded-lg", "border-border", "bg-surface", "shadow-sm"} <= _classes(card[1])
    assert "Details" in text["card"]
    assert "Shown to all" in text["card"]
    assert ("h3", {"class": "text-sm font-semibold"}) in found["card"]
    assert ("p", {"id": "card-body"}) in found["card"]
    tag, attrs = found["link-card"][0]
    assert tag == "a"
    assert attrs["href"] == "/c"
    assert "hover:border-fg-subtle" in _classes(attrs)
    assert found["link-card"][1][0] == "table"


def test_menu_markup(rendered: tuple[dict[str, list[Element]], dict[str, str], str]) -> None:
    found, text, _ = rendered
    root = found["menu"][0][1]
    assert root["x-data"] == 'hxPopover("menu")'
    assert root["@click.outside"] == "close(false)"
    assert "@keydown.escape" in root
    trigger = _only(found["menu"], "button")[0]
    assert trigger["id"] == "row-menu-1-trigger"
    assert trigger["aria-haspopup"] == "menu"
    assert trigger["aria-expanded"] == "false"
    assert trigger[":aria-expanded"] == "expanded"
    assert trigger["aria-controls"] == "row-menu-1"
    assert trigger["aria-label"] == "Row actions"
    assert "size-8" in _classes(trigger)
    (panel,) = [a for _, a in found["menu"] if a.get("id") == "row-menu-1"]
    assert panel["role"] == "menu"
    assert panel["aria-labelledby"] == "row-menu-1-trigger"
    assert panel["x-anchor.bottom-end.offset.4.fixed"] == "$refs.trigger"
    assert panel["x-show"] == "expanded"
    assert {"bg-popover", "shadow-md", "border-border"} <= _classes(panel)
    assert "@keydown.down.prevent" in panel
    assert "@keydown.home.prevent" in panel
    items = [a for _, a in found["menu"] if a.get("role") == "menuitem"]
    assert [(i.get("href"), i.get("tabindex")) for i in items] == [
        ("/e", "-1"),
        (None, "-1"),
        (None, "-1"),
    ]
    assert items[1]["aria-disabled"] == "true"
    assert {"text-danger", "focus:bg-danger-soft"} <= _classes(items[2])
    assert items[2]["@click"] == "del()"
    assert [a for _, a in found["menu"] if a.get("role") == "separator"]
    assert [a for _, a in found["menu"] if a.get("role") == "presentation"]
    assert "Record" in text["menu"]
    assert "E" in text["menu"]


def test_popover_markup(rendered: tuple[dict[str, list[Element]], dict[str, str], str]) -> None:
    found, text, _ = rendered
    trigger = _only(found["popover"], "button")[0]
    assert trigger["aria-haspopup"] == "dialog"
    assert trigger["aria-controls"] == "filter-status"
    assert "aria-label" not in trigger
    assert {"border-border", "h-9"} <= _classes(trigger)
    assert text["popover"].strip() == "Status"
    (panel,) = [a for _, a in found["popover"] if a.get("id") == "filter-status"]
    assert panel["role"] == "dialog"
    assert panel["x-anchor.bottom-start.offset.4.fixed"] == "$refs.trigger"
    assert {"w-56", "p-3", "bg-popover"} <= _classes(panel)
    assert ("input", {"name": "f.status"}) in found["popover"]


def test_dialog_markup(rendered: tuple[dict[str, list[Element]], dict[str, str], str]) -> None:
    found, text, _ = rendered
    root = found["dialog"][0][1]
    assert root["x-show"] == "confirm"
    overlay = found["dialog"][1][1]
    assert "bg-overlay" in _classes(overlay)
    assert overlay["@click"] == "dismiss()"
    (panel,) = [a for _, a in found["dialog"] if a.get("role") == "dialog"]
    assert panel["id"] == "confirm"
    assert panel["aria-modal"] == "true"
    assert panel["aria-labelledby"] == "confirm-title"
    assert panel["aria-describedby"] == "confirm-description"
    assert panel["x-trap.inert.noscroll"] == "confirm"
    assert panel["@keydown.escape.prevent.stop"] == "dismiss()"
    assert {"max-w-sm", "shadow-lg", "bg-surface"} <= _classes(panel)
    assert ("h2", {"id": "confirm-title", "class": "text-base font-semibold leading-tight"}) in (
        found["dialog"]
    )
    assert "Delete task?" in text["dialog"]
    assert "This cannot be undone." in text["dialog"]
    cancel, delete, close = _only(found["dialog"], "button")
    assert "autofocus" in cancel
    assert "bg-danger" in _classes(delete)
    assert close["aria-label"] == "Close"
    assert close["@click"] == "dismiss()"
    plain = found["plain-dialog"]
    assert not _only(plain, "button")
    assert next(a for t, a in plain if t == "h2")["x-text"] == "t"
    assert "aria-describedby" not in next(a for _, a in plain if a.get("role") == "dialog")


def test_empty_state_stat_and_alert(
    rendered: tuple[dict[str, list[Element]], dict[str, str], str],
) -> None:
    found, text, _ = rendered
    assert "border-dashed" in _classes(found["empty"][0][1])
    assert "No tasks yet" in text["empty"]
    assert "Create one." in text["empty"]
    assert _only(found["empty"], "a")[0]["href"] == "/n"
    first, second = [
        a for t, a in found["stat"] if t in ("a", "div") and "rounded-lg" in _classes(a)
    ]
    assert first["href"] == "/s"
    assert "href" not in second
    assert "12" in text["stat"]
    assert "3 today" in text["stat"]
    assert "—" in text["stat"]
    assert [a for _, a in found["stat"] if "bg-accent-soft" in _classes(a)]
    danger, success = [a for _, a in found["alerts"] if a.get("role")]
    assert danger["role"] == "alert"
    assert {"bg-danger-soft", "text-danger"} <= _classes(danger)
    assert success["role"] == "status"
    assert "bg-success-soft" in _classes(success)
    assert "Error" in text["alerts"]


def test_tooltip_and_kbd(rendered: tuple[dict[str, list[Element]], dict[str, str], str]) -> None:
    found, text, _ = rendered
    wrapper = found["tooltip"][0][1]
    assert wrapper["x-id"] == "['hx-tooltip']"
    assert wrapper["@mouseenter"] == "tip = !!(collapsed)"
    assert "aria-describedby" in (wrapper["x-init"] or "")
    assert found["tooltip"][1] == ("a", {"href": "/u"})
    tip = found["tooltip"][2][1]
    assert tip["role"] == "tooltip"
    assert tip["x-anchor.right.offset.6.fixed"] == "$el.previousElementSibling"
    assert "Users" in text["tooltip"]
    assert found["kbd"][0][0] == "kbd"
    assert text["kbd"] == "⌘K"


def test_layout_defines_the_popover_component(
    rendered: tuple[dict[str, list[Element]], dict[str, str], str],
) -> None:
    _, _, html = rendered
    assert 'Alpine.data("hxPopover"' in html


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('{{ m.button("x", "fancy") }}', "Unknown button variant 'fancy'"),
        ('{{ m.button("x", size="xl") }}', "Unknown button size 'xl'"),
        ('{{ m.badge("x", "info") }}', "Unknown badge tone 'info'"),
        ('{{ m.alert("x", "info") }}', "Unknown alert tone 'info'"),
        ('{% call m.menu("m", "x", placement="middle") %}{% endcall %}', "Unknown placement"),
        ('{% call m.popover("p", "x", size="xl") %}{% endcall %}', "Unknown popover size"),
        ('{{ m.menu_item("x", tone="accent") }}', "Unknown menu item tone"),
        ('{% call m.dialog("d", "x", size="xl") %}{% endcall %}', "Unknown dialog size"),
        ('{{ m.button("x", attrs={"class": "y"}) }}', "class argument"),
        ('{{ m.button("x", attrs={"on click": "y"}) }}', "Invalid attribute name"),
    ],
)
def test_invalid_arguments_raise(factory: AppFactory, source: str, message: str) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    template = admin.templates.from_string('{% import "_macros.html" as m %}' + source)
    with pytest.raises(ValueError, match=message):
        template.render()


def test_html_attrs_rules() -> None:
    rendered = str(
        html_attrs(
            {"@click": 'a("x")', "hidden": True, "title": None},
            {"hx_get": "/q?a=1&b=2", "disabled": False, "data_n": 3},
        )
    )
    assert rendered == ' @click="a(&#34;x&#34;)" hidden hx-get="/q?a=1&amp;b=2" data-n="3"'
    assert str(html_attrs()) == ""
