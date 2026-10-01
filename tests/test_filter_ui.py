import re
from collections.abc import Callable, Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import ActionResult, HxAdmin, ModelView, action
from tests.conftest import AppFactory, Post, Tag, User, allow_all
from tests.js import needs_node, run_layout_js
from tests.test_filters import seed

type MakeClient = Callable[[FastAPI], TestClient]
HX = {"HX-Request": "true"}


class PostView(ModelView[Post]):
    model = Post
    list_columns = ("title", "status", "score", "author")
    list_filters = ("status", "score", "published_at", "title", "author")
    default_sort = ("title", "asc")

    @action("touch", bulk=True)
    async def touch(
        self, request: Request, session: AsyncSession, objs: Sequence[Post]
    ) -> ActionResult:
        return ActionResult.message(f"Touched {len(objs)}")


class UserView(ModelView[User]):
    model = User


class HiddenUserView(ModelView[User]):
    model = User

    def is_accessible(self, request: Request) -> bool:
        return False


class TagView(ModelView[Tag]):
    model = Tag


async def seed_tagged(session: AsyncSession) -> None:
    await seed(session)
    session.add(Tag(name="all", posts=list((await session.scalars(select(Post))).all())))


def build(factory: AppFactory, user_view: type[ModelView[User]] = UserView) -> FastAPI:
    app = factory.app(seed=seed_tagged)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(PostView)
    admin.register(user_view)
    admin.register(TagView)
    return app


def test_panel_reflects_the_current_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published&f.score.min=1&f.author=2").text
    assert 'id="list-filters"' in html
    assert 'id="filter-status-summary"' in html
    assert 'id="filter-score-summary"' in html
    assert 'id="filter-author-summary"' in html
    assert "≥ 1" in html
    assert "bob@x.io" in html
    assert 'name="f.status" value="published" checked class="hx-filter-pick"' in html
    assert 'name="f.status" value="draft" class="hx-filter-pick"' in html
    assert 'name="f.score.min" value="1"' in html
    assert 'name="f.author" value="1" class="hx-filter-pick"> ada@x.io' in html
    assert 'name="f.author" value="2" checked class="hx-filter-pick"> bob@x.io' in html
    assert 'name="f.published_at.empty"' in html
    assert 'name="f.status.empty"' not in html
    assert '<button type="button" class="{{' not in html
    assert "Showing 1\N{EN DASH}1 of 1" in html


def test_filter_buttons_start_inactive_without_filters(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
        users = client.get("/admin/user/").text
    assert 'id="filter-status-summary"' in html
    assert "border-dashed" in html
    assert '<span id="list-reset"></span>' in html
    assert 'id="filter-' not in users


def test_toolbar_submits_on_filter_changes(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    assert (
        'hx-trigger="input changed delay:300ms from:#list-q, input delay:300ms '
        'target:.hx-filter-text, change target:.hx-filter-pick, submit"'
    ) in html
    assert 'hx-include="#list-state"' in html
    assert "window.hxadminClearFilter = function (key)" in html
    assert "onclick" not in html


def test_only_the_toolbar_search_box_triggers_the_list(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    assert html.count('id="list-q"') == 1
    toolbar = html[
        html.index('id="list-filters"') : html.index("</form>", html.index('id="list-filters"'))
    ]
    assert 'id="list-q"' in toolbar
    assert "from:[name=q]" not in html


def test_reset_button_clears_every_active_filter(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published&f.author=2").text
    assert '@click="hxadminResetFilters()"' in html
    assert '@click="hxadminClearFilter(&#34;f.status&#34;)"' in html
    assert '@click="hxadminClearFilter(&#34;f.author&#34;)"' in html


FORM = """
const submitted = [];
function input(name, value, type) {
  return { name, value, type: type || "text", checked: type === "checkbox", dispatchEvent() {} };
}
const els = [
  input("q", "zz"), input("sort", "title"), input("f.due", "x"), input("f.due.min", "1"),
  input("f.due_date.min", "2026-01-01"), input("f.status", "todo", "checkbox"),
];
document.elements["list-filters"] = { elements: els, requestSubmit() { submitted.push(true); } };
const value = (e) => (e.type === "checkbox" ? e.checked : e.value);
const state = () => Object.fromEntries(els.map((e) => [e.name, value(e)]));
"""


@needs_node
def test_clearing_one_filter_leaves_filters_sharing_its_prefix(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    assert "[name^=" not in html
    assert '@hxadmin-clear="reset()"' in html
    probe = (
        FORM
        + 'window.hxadminClearFilter("f.due");'
        + "console.log(JSON.stringify([state(), submitted.length]));"
    )
    assert run_layout_js(html, probe) == [
        {
            "q": "zz",
            "sort": "title",
            "f.due": "",
            "f.due.min": "",
            "f.due_date.min": "2026-01-01",
            "f.status": True,
        },
        1,
    ]


@needs_node
def test_reset_filters_keeps_search_and_reset_list_clears_it(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    filters = run_layout_js(
        html, FORM + "window.hxadminResetFilters(); console.log(JSON.stringify(state()));"
    )
    assert filters == {
        "q": "zz",
        "sort": "title",
        "f.due": "",
        "f.due.min": "",
        "f.due_date.min": "",
        "f.status": False,
    }
    everything = run_layout_js(
        html, FORM + "window.hxadminResetList(); console.log(JSON.stringify(state()));"
    )
    assert everything == {
        "q": "",
        "sort": "title",
        "f.due": "",
        "f.due.min": "",
        "f.due_date.min": "",
        "f.status": False,
    }


def test_partial_swaps_filter_summaries_out_of_band(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.author=2&f.title=a", headers=HX).text
    assert 'id="list-filters"' not in html
    assert 'id="filter-author-summary" hx-swap-oob="true"' in html
    assert 'id="filter-title-summary" hx-swap-oob="true"' in html
    assert 'id="list-reset" hx-swap-oob="true"' in html
    assert "bob@x.io" in html
    assert "Showing 1\N{EN DASH}2 of 2" in html


def test_sort_and_page_links_keep_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published", headers=HX).text
    assert '?f.status=published&amp;sort=title&amp;dir=desc&amp;page=1&amp;size=25"' in html
    assert 'hx-get="/admin/post/?f.status=published&amp;sort=title&amp;dir=asc&amp;page=1"' in html


def test_relation_filter_hidden_when_target_is_inaccessible(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, HiddenUserView)) as client:
        html = client.get("/admin/post/?f.author=2").text
    assert 'name="f.author"' not in html
    assert 'id="filter-author-summary"' not in html
    assert "Showing 1\N{EN DASH}3 of 3" in html


def test_action_rerender_keeps_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/post/action/touch",
            data={"pks": ["1"], "_from": "list"},
            headers={**HX, "HX-Current-URL": "http://testserver/admin/post/?f.status=published"},
        )
    assert response.status_code == 200
    assert "Showing 1\N{EN DASH}2 of 2" in response.text
    assert 'id="filter-status-summary" hx-swap-oob="true"' in response.text
    assert "published" in response.text


def test_related_tab_ignores_filters_of_a_hidden_target(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, HiddenUserView)) as client:
        html = client.get("/admin/tag/_related/1/posts?f.author=1").text
    assert all(title in html for title in ("Alpha", "Beta", "Gamma 100%"))


def test_related_tab_reads_no_filters(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/tag/_related/1/posts?f.status=draft").text
    assert "Showing 1\N{EN DASH}3 of 3" in html


class CountingUserView(ModelView[User]):
    model = User
    queries = 0

    def get_query(self, request: Request) -> Select[tuple[User]]:
        CountingUserView.queries += 1
        return super().get_query(request)


def test_relation_filter_scope_is_built_once_per_render(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, CountingUserView)) as client:
        CountingUserView.queries = 0
        client.get("/admin/post/?f.author=2")
        full = CountingUserView.queries
        CountingUserView.queries = 0
        client.get("/admin/post/?f.status=draft", headers=HX)
        partial = CountingUserView.queries
    assert (full, partial) == (1, 0)


def test_date_range_filters_use_the_date_picker(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.published_at.min=2026-01-01T09:00").text
    assert 'type="datetime-local"' not in html
    assert (
        'x-data="dateInput(&#34;datetime&#34;, &#34;2026-01-01T09:00&#34;, '
        '&#34;MM/dd/yyyy HH:mm&#34;)"' in html
    )
    assert (
        'name="f.published_at.min" value="2026-01-01T09:00" :value="value" x-ref="hidden"'
        ' class="hx-filter-pick"'
    ) in html
    assert 'name="f.published_at.max" value="" :value="value" x-ref="hidden"' in html
    assert 'id="filter-published_at-min"' in html
    assert 'name="f.score.min" value="" aria-label="Score from" step="any"' in html


def test_toolbar_controls_share_one_height(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    toolbar = html[
        html.index('id="list-filters"') : html.index("</form>", html.index('id="list-filters"'))
    ]
    search = re.search(r'<input type="search" id="list-q"[^>]*class="([^"]*)"', toolbar)
    pills = re.findall(r'id="filter-\w+-summary"[^>]*class="([^"]*)"', toolbar)
    assert search is not None
    assert len(pills) == 5
    heights = {
        c for classes in (search.group(1), *pills) for c in classes.split() if c.startswith("h-")
    }
    assert heights == {"h-8"}


@needs_node
def test_toolbar_requests_drop_empty_params(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    probe = """
    function run(id, method) {
      const body = new FormData();
      body.append("q", ""); body.append("f.status", ""); body.append("f.status", "todo");
      body.append("f.due.min", ""); body.append("size", "25");
      const ctx = { sourceElement: { id }, request: { method, body } };
      fire("htmx:config:request", { detail: { ctx } });
      return Array.from(new Set(body.keys()));
    }
    const runs = [run("list-filters", "GET"), run("list-filters", "POST"), run("other", "GET")];
    console.log(JSON.stringify(runs));
    """
    assert run_layout_js(html, probe) == [
        ["f.status", "size"],
        ["q", "f.status", "f.due.min", "size"],
        ["q", "f.status", "f.due.min", "size"],
    ]


@needs_node
def test_filter_calendars_open_beside_their_panel(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/").text
    assert "popover ? { position: dates.besidePanel(popover) } : {}" in html
    probe = """
    function place(innerWidth, box) {
      window.innerWidth = innerWidth;
      const panel = { clientTop: 0, clientLeft: 0, getBoundingClientRect: () => box };
      const o = {
        $target: { getBoundingClientRect: () => ({ top: box.top + 40 }) },
        $datepicker: { offsetWidth: 250, style: {} },
        $pointer: { style: {} },
      };
      window.hxadminDates.besidePanel(panel)(o);
      return [o.$datepicker.style.left, o.$datepicker.style.top, o.$pointer.style.display];
    }
    console.log(JSON.stringify([
      place(1440, { left: 100, right: 400, width: 300, top: 50, height: 200 }),
      place(1440, { left: 1100, right: 1400, width: 300, top: 50, height: 200 }),
      place(390, { left: 2, right: 388, width: 386, top: 50, height: 200 }),
    ]));
    """
    assert run_layout_js(html, probe) == [
        ["308px", "40px", "none"],
        ["-258px", "40px", "none"],
        ["6px", "208px", "none"],
    ]
