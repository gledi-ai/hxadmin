import re
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from hxadmin.export import XLSX_MEDIA_TYPE
from hxadmin.toasts import FLASH_COOKIE
from tests.conftest import AppFactory, Post, User, allow_all
from tests.test_export import read_sheet
from tests.test_filters import seed

type MakeClient = Callable[[FastAPI], TestClient]

HEADER = "Title,Status,Score,Author\r\n"
ALPHA = "Alpha,published,1.0,ada@x.io\r\n"
BETA = "Beta,draft,2.5,bob@x.io\r\n"
GAMMA = "Gamma 100%,published,4.0,bob@x.io\r\n"


class PostView(ModelView[Post]):
    model = Post
    list_columns = ("title", "status", "score", "author")
    list_filters = ("status",)
    searchable = ("title",)
    default_sort = ("title", "asc")
    export_formats = ("csv",)


class UserView(ModelView[User]):
    model = User


def build(factory: AppFactory, view: type[ModelView[Post]] = PostView) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(view)
    admin.register(UserView)
    return app


def test_csv_exports_the_list_as_shown_across_pages(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.get(
            "/admin/post/_export/csv?f.status=published&sort=title&dir=desc&page=2&size=1"
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert re.fullmatch(
        r'attachment; filename="post-\d{8}-\d{6}\.csv"', response.headers["content-disposition"]
    )
    assert response.content.decode("utf-8-sig") == HEADER + GAMMA + ALPHA


def test_csv_export_applies_search(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        body = client.get("/admin/post/_export/csv?q=bet").content.decode("utf-8-sig")
    assert body == HEADER + BETA


def test_selection_export_keeps_order_and_ignores_filters(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/post/_export/csv?pks=3&pks=1&pks=1&pks=999&f.status=draft")
    assert response.content.decode("utf-8-sig") == HEADER + GAMMA + ALPHA


def test_export_is_scoped_by_get_query(factory: AppFactory, make_client: MakeClient) -> None:
    class ScopedPostView(PostView):
        def get_query(self, request: Request) -> Select[tuple[Post]]:
            return super().get_query(request).where(Post.title != "Beta")

    with make_client(build(factory, ScopedPostView)) as client:
        listed = client.get("/admin/post/_export/csv").content.decode("utf-8-sig")
        picked = client.get("/admin/post/_export/csv?pks=2").content.decode("utf-8-sig")
    assert listed == HEADER + ALPHA + GAMMA
    assert picked == HEADER


def test_export_routing_errors(factory: AppFactory, make_client: MakeClient) -> None:
    class LockedPostView(PostView):
        def is_accessible(self, request: Request) -> bool:
            return False

    with make_client(build(factory)) as client:
        assert client.get("/admin/post/_export/xlsx").status_code == 404
        assert client.get("/admin/post/_export/pdf").status_code == 404
        assert client.get("/admin/nope/_export/csv").status_code == 404
        assert client.get("/admin/user/_export/csv").status_code == 404
    with make_client(build(AppFactory(), LockedPostView)) as client:
        assert client.get("/admin/post/_export/csv").status_code == 403


def test_export_over_the_row_limit_returns_to_the_list(
    factory: AppFactory, make_client: MakeClient
) -> None:
    class CappedPostView(PostView):
        export_max_rows = 2

    with make_client(build(factory, CappedPostView)) as client:
        over = client.get(
            "/admin/post/_export/csv?f.status=draft&f.status=published", follow_redirects=False
        )
        page = client.get(over.headers["location"])
        within = client.get("/admin/post/_export/csv?f.status=published")
    assert over.status_code == 303
    assert over.headers["location"] == "/admin/post/?f.status=draft&f.status=published"
    assert FLASH_COOKIE in over.headers["set-cookie"]
    assert "Export is limited to 2 rows; narrow the search or filters." in page.text
    assert within.status_code == 200


def test_xlsx_export(factory: AppFactory, make_client: MakeClient) -> None:
    class XlsxPostView(PostView):
        export_formats = ("csv", "xlsx")

    with make_client(build(factory, XlsxPostView)) as client:
        response = client.get("/admin/post/_export/xlsx?f.status=published")
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert response.headers["content-disposition"].endswith('.xlsx"')
    name, cells, _ = read_sheet(response.content)
    assert name == "Posts"
    assert cells["A1"] == ("s", "Title", True, False)
    assert cells["A2"] == ("s", "Alpha", False, False)
    assert cells["C3"] == (None, "4", False, False)
    assert cells["D3"] == ("s", "bob@x.io", False, False)
    assert "A4" not in cells


def test_list_offers_export_links_and_selection_export(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/?f.status=published").text
        users = client.get("/admin/user/").text
        related = client.get("/admin/user/_related/2/posts").text
    assert 'href="/admin/post/_export/csv?f.status=published&amp;sort=title&amp;dir=asc"' in html
    assert 'id="bulk"' in html
    assert 'formaction="/admin/post/_export/csv"' in html
    assert 'name="pks" value="1" form="bulk"' in html
    assert "_export" not in users
    assert 'id="bulk"' not in users
    assert "_export" not in related
