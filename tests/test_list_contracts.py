"""Markup contracts of the list page that the phase 6 spec names."""

import re
from collections.abc import Callable, Sequence
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import ActionResult, HxAdmin, ModelView, action
from hxadmin.export import ExportFormat
from tests.conftest import AppFactory, Post, User, allow_all
from tests.test_filters import seed

type MakeClient = Callable[[FastAPI], TestClient]
HX = {"HX-Request": "true"}


class PostView(ModelView[Post]):
    model = Post
    list_columns = ("title", "status", "score", "author")
    list_filters = ("status", "score", "published_at", "title", "author")
    export_formats: ClassVar[tuple[ExportFormat, ...]] = ("csv", "xlsx")
    default_sort = ("title", "asc")

    @action("publish")
    async def publish(self, request: Request, session: AsyncSession, obj: Post) -> ActionResult:
        return ActionResult.message("ok")

    @action("secret")
    async def secret(self, request: Request, session: AsyncSession, obj: Post) -> ActionResult:
        return ActionResult.message("ok")

    @action("touch", bulk=True)
    async def touch(
        self, request: Request, session: AsyncSession, objs: Sequence[Post]
    ) -> ActionResult:
        return ActionResult.message("ok")

    def is_action_allowed(self, request: Request, name: str) -> bool:
        return name != "secret"


class UserView(ModelView[User]):
    model = User


def build(factory: AppFactory, post_view: type[ModelView[Post]] = PostView) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(post_view)
    admin.register(UserView)
    return app


def summary(html: str, name: str) -> str:
    """The visible text of a filter button's summary, badges flattened to their text."""
    start = html.index(f'id="filter-{name}-summary"')
    span = html[start : html.index("</button>", start)]
    parts = span.split('<span class="mx-0.5', 1)
    if len(parts) == 1:
        return ""
    text = re.sub(r"<svg.*?</svg>", "", parts[1], flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text[text.index(">") + 1 :])
    return " ".join(text.split())


@pytest.mark.parametrize(
    ("query", "name", "expected"),
    [
        ("f.status=published", "status", "published"),
        ("f.status=published&f.status=draft", "status", "published draft"),
        ("f.author=1&f.author=2&f.author=3", "author", "3 selected"),
        ("f.author=2", "author", "bob@x.io"),
        ("f.score.min=2&f.score.max=5", "score", "2\N{EN DASH}5"),
        ("f.score.min=2", "score", "≥ 2"),
        ("f.score.max=5", "score", "≤ 5"),
        ("f.published_at.empty=1", "published_at", "Empty"),
        (
            "f.published_at.min=2026-01-01T00:00&f.published_at.empty=1",
            "published_at",
            "≥ 2026-01-01T00:00 + Empty",
        ),
        ("f.title=al", "title", "“al”"),
        ("f.title=", "title", ""),
    ],
)
def test_filter_button_summaries(
    factory: AppFactory, make_client: MakeClient, query: str, name: str, expected: str
) -> None:
    with make_client(build(factory)) as client:
        html = client.get(f"/admin/post/?{query}").text
        partial = client.get(f"/admin/post/?{query}", headers=HX).text
    assert summary(html, name) == expected
    oob = partial[partial.index(f'id="filter-{name}-summary"') - 6 :]
    assert 'hx-swap-oob="true"' in oob[: oob.index(">")]


def test_selected_choice_values_render_as_badges(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published&f.author=2").text
    start = html.index('id="filter-status-summary"')
    assert 'data-tone="neutral">published</span>' in html[start : html.index("</button>", start)]


def classes_of(tag: str) -> set[str]:
    match = re.search(r'class="([^"]*)"', tag)
    return set(match.group(1).split()) if match else set()


def test_numeric_columns_are_right_aligned_with_tabular_numbers(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    table = html[html.index("<table") : html.index("</table>")]
    heads = re.findall(r"<th\b[^>]*>", table)[1:]
    rows = re.findall(r"<tr\b.*?</tr>", table[table.index("<tbody") :], re.DOTALL)
    cells = re.findall(r"<td\b[^>]*>", rows[0])[1:]
    names = ("title", "status", "score", "author")
    columns = dict(zip(names, zip(heads[:4], cells[:4], strict=True), strict=True))
    for name, (head, cell) in columns.items():
        numeric = name == "score"
        assert ("text-right" in classes_of(head)) is numeric, name
        assert ({"text-right", "tabular-nums"} <= classes_of(cell)) is numeric, name


def export_links(html: str) -> list[str]:
    start = html.index('id="list-export-items"')
    block = html[start : html.index("</div>", start)]
    return re.findall(r'href="([^"]+)"', block)


def test_export_links_carry_the_current_query(factory: AppFactory, make_client: MakeClient) -> None:
    query = "q=al&f.status=published&sort=score&dir=desc&page=2&size=25"
    with make_client(build(factory)) as client:
        html = client.get(f"/admin/post/?{query}").text
        partial = client.get(f"/admin/post/?{query}", headers=HX).text
    for links in (export_links(html), export_links(partial)):
        assert [link.split("?")[0] for link in links] == [
            "/admin/post/_export/csv",
            "/admin/post/_export/xlsx",
        ]
        for link in links:
            params = link.split("?", 1)[1].replace("&amp;", "&")
            assert "q=al" in params
            assert "f.status=published" in params
            assert "sort=score" in params
            assert "dir=desc" in params
            assert "page=" not in params
            assert "size=" not in params
    oob = partial[partial.index('id="list-export-items"') - 6 :]
    assert 'hx-swap-oob="true"' in oob[: oob.index(">")]


def row_menu(html: str, pk: int) -> str:
    start = html.index(f'id="row-menu-{pk}"')
    return html[start : html.index("</td>", start)]


def test_row_menu_lists_permitted_actions_and_delete_last(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    menu = row_menu(html, 1)
    labels = [
        " ".join(re.sub(r"<svg.*?</svg>|<[^>]+>", " ", item, flags=re.DOTALL).split())
        for item in re.findall(r'role="menuitem".*?>(.*?)</(?:a|button)>', menu, flags=re.DOTALL)
    ]
    assert labels == ["View", "Edit", "Publish", "Delete"]
    assert "/action/secret" not in html
    assert "/action/touch" not in menu
    assert 'role="separator"' in menu


class NoDeletePostView(PostView):
    can_delete = False


def test_row_menu_omits_delete_without_can_delete(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, NoDeletePostView)) as client:
        html = client.get("/admin/post/").text
    menu = row_menu(html, 1)
    assert ">Delete<" not in menu
    assert "/delete" not in html
    assert 'role="separator"' not in menu


def test_each_selected_pk_has_exactly_one_enabled_checkbox(
    factory: AppFactory, make_client: MakeClient
) -> None:
    """Card and table checkboxes are twins; `wide` enables exactly one of each pair."""
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    boxes = re.findall(r'<input type="checkbox" id="pk-(mobile|desktop)-(\d+)"([^>]*)>', html)
    pairs: dict[str, dict[str, str]] = {}
    for where, pk, attrs in boxes:
        assert 'name="pks"' in attrs
        assert 'form="bulk"' in attrs
        assert f'value="{pk}"' in attrs
        disabled = re.search(r':disabled="([^"]+)"', attrs)
        assert disabled is not None
        pairs.setdefault(pk, {})[where] = disabled.group(1)
    assert len(pairs) == 3
    assert all(p == {"mobile": "wide", "desktop": "!wide"} for p in pairs.values())


def test_table_header_sticks_inside_its_scrolling_card(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    thead = re.search(r"<thead\b[^>]*>", html)
    assert thead is not None
    assert {"sticky", "top-0"} <= classes_of(thead.group(0))
    card = html[: html.index("<table")]
    card = card[card.rindex("<div") :]
    assert "overflow-auto" in classes_of(card)
    assert any(c.startswith("max-h-") for c in classes_of(card))


def test_mobile_list_has_select_all_and_room_for_the_bulk_bar(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    assert 'data-select-all="mobile"' in html
    assert "input[id^=pk-mobile-]:not(:disabled)" in html
    assert ":class=\"count > 0 && 'pb-24'\"" in html.replace("&#39;", "'")


def test_mobile_toolbar_puts_export_beside_search_and_filters_below(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    start = html.index('id="list-filters"')
    toolbar = html[start : html.index("</form>", start)]
    pills = re.search(r'<div class="([^"]*overflow-x-auto[^"]*)"', toolbar)
    assert pills is not None
    assert {"max-sm:order-last", "max-sm:basis-full"} <= set(pills.group(1).split())


def test_both_select_all_boxes_share_one_macro(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    boxes = re.findall(r'<input[^>]*data-select-all="(\w+)"[^>]*data-select-scope="([^"]+)"', html)
    assert boxes == [
        ("mobile", "input[id^=pk-mobile-]:not(:disabled)"),
        ("desktop", "input[name=pks]:not(:disabled)"),
    ]
