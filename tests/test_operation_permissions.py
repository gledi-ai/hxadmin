from collections.abc import Callable

from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from starlette.requests import Request

from hxadmin import HxAdmin, ModelOperation, ModelView
from tests.conftest import AppFactory, Post, User
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]

STAFF = {"X-Test-Role": "staff"}
EDITOR = {"X-Test-Role": "editor"}
LIST_ONLY = {"X-Test-Role": "list-only"}
ADMIN = {"X-Test-Role": "admin"}


def build(factory: AppFactory) -> FastAPI:
    def auth(request: Request) -> str:
        return request.headers["X-Test-Role"]

    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=auth)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        searchable = ("title",)
        export_formats = ("csv",)

        def is_operation_allowed(self, request: Request, operation: ModelOperation) -> bool:
            role = request.state.hxadmin_user
            return (
                role == "admin"
                or (role == "editor" and operation in {"view", "edit"})
                or (role == "staff" and operation == "view")
            )

    @admin.register
    class UserView(ModelView[User]):
        model = User
        can_create = False

    return app


def test_read_only_staff_can_browse_but_cannot_use_writes_or_export(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        listing = client.get("/admin/post/", headers=STAFF)
        fragment = client.get("/admin/post/", headers={**STAFF, "HX-Request": "true"})
        detail = client.get("/admin/post/1", headers=STAFF)
        assert listing.status_code == detail.status_code == status.HTTP_200_OK
        assert 'href="/admin/post/1"' in listing.text
        for response in (listing, fragment, detail):
            assert "/admin/post/new" not in response.text
            assert "/admin/post/1/edit" not in response.text
            assert "/admin/post/1/delete" not in response.text
            assert "/admin/post/_export/csv" not in response.text
            assert 'name="pks"' not in response.text

        for method, path in (
            ("GET", "/new"),
            ("POST", "/new"),
            ("GET", "/1/edit"),
            ("POST", "/1/edit"),
            ("POST", "/1/delete"),
            ("GET", "/_lookup/author"),
            ("GET", "/_export/csv"),
            ("GET", "/_export/csv?pks=1"),
        ):
            response = client.request(method, f"/admin/post{path}", headers=STAFF)
            assert response.status_code == status.HTTP_403_FORBIDDEN

        assert client.get("/admin/post/_export/xlsx", headers=STAFF).status_code == 404
        assert client.get("/admin/post/_export/csv", headers=ADMIN).status_code == 200
        assert "/admin/post/_export/csv" in client.get("/admin/post/", headers=ADMIN).text
        assert client.get("/admin/user/new", headers=ADMIN).status_code == 403


def test_editor_can_save_without_create_permission(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        form = client.get("/admin/post/1/edit", headers=EDITOR)
        assert form.status_code == status.HTTP_200_OK
        assert 'value="another"' not in form.text

        saved = client.post(
            "/admin/post/1/edit",
            data={
                "title": "Edited",
                "status": "draft",
                "score": "0",
                "author": "1",
                "_then": "another",
            },
            headers=EDITOR,
            follow_redirects=False,
        )
        assert saved.status_code == status.HTTP_303_SEE_OTHER
        assert saved.headers["Location"] == "/admin/post/1"
        assert "Edited" in client.get("/admin/post/1", headers=EDITOR).text


def test_detail_permission_covers_links_and_related_tabs(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        listing = client.get("/admin/post/", headers=LIST_ONLY)
        palette = client.get("/admin/_palette?q=Hello", headers=LIST_ONLY)
        assert "Hello" in listing.text
        assert "Hello" in palette.text
        for response in (listing, palette):
            assert 'href="/admin/post/1"' not in response.text
        for path in ("/admin/post/1", "/admin/post/_related/1/tags"):
            assert client.get(path, headers=LIST_ONLY).status_code == 403
            assert client.get(path, headers=STAFF).status_code == 200
