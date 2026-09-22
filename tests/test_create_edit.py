from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, Post, Tag, User, Vote, allow_all
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]

POST_DATA = {"title": "New", "status": "draft", "author": "1", "tags": ["1"]}


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class UserView(ModelView[User]):
        model = User
        searchable = ("email",)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        searchable = ("title",)
        detail_columns = ("title", "status", "published_at", "author", "tags")

    @admin.register
    class VoteView(ModelView[Vote]):
        model = Vote

    @admin.register
    class TagView(ModelView[Tag]):
        model = Tag

        def display(self, obj: Tag) -> str:
            return obj.name

    return app


def test_create_form_full_page(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/post/new")
    html = response.text
    assert response.status_code == 200
    assert "<html" in html
    assert "<form" in html
    assert 'hx-post="/admin/post/new"' in html
    assert 'name="title"' in html
    assert '<select name="status"' in html
    assert 'option value="draft" selected' in html
    assert 'name="id"' not in html
    assert 'name="author_id"' not in html
    assert "Save and add another" in html


def test_create_form_partial(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/new", headers={"HX-Request": "true"}).text
    assert "<html" not in html
    assert html.lstrip().startswith("<form")


def test_create_success_redirects_to_detail(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/post/new", data=POST_DATA, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/post/2"
        detail = client.get("/admin/post/2").text
        listing = client.get("/admin/post/").text
    assert "New" in detail
    assert 'hx-get="/admin/post/_related/2/tags"' in detail
    assert "Showing 1\u20132 of 2" in listing


def test_create_htmx_success_sends_hx_redirect(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/post/new",
            data=POST_DATA,
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/admin/post/2"


def test_create_save_and_add_another(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/post/new", data={**POST_DATA, "_then": "another"}, follow_redirects=False
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/post/new"


def test_create_validation_errors_rerender_422(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        full = client.post("/admin/post/new", data={"title": "", "status": "nope"})
        partial = client.post(
            "/admin/post/new",
            data={"title": "", "status": "nope"},
            headers={"HX-Request": "true"},
        )
    assert full.status_code == 422
    assert "This field is required." in full.text
    assert 'aria-invalid="true"' in full.text
    assert "<form" in full.text
    assert "<html" in full.text
    assert partial.status_code == 422
    assert "<html" not in partial.text


def test_create_unknown_relation_pk_is_field_error(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/post/new", data={**POST_DATA, "author": "999"})
    html = response.text
    assert response.status_code == 422
    assert "Unknown selection." in html
    assert html.index("Author") < html.index("Unknown selection.")


def test_create_integrity_error_is_form_error(factory: AppFactory, make_client: MakeClient) -> None:
    data = {"email": "new@x.io", "active": "on"}
    with make_client(build(factory)) as client:
        first = client.post("/admin/user/new", data=data, follow_redirects=False)
        second = client.post("/admin/user/new", data=data, follow_redirects=False)
        listing = client.get("/admin/user/").text
    assert first.status_code == 303
    assert second.status_code == 422
    assert 'role="alert"' in second.text
    assert "Showing 1\u20133 of 3" in listing


def test_edit_form_prefills(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/post/1/edit")
    html = response.text
    assert response.status_code == 200
    assert 'value="Hello"' in html
    assert "disabled" in html
    assert '{"label": "ada@x.io", "pk": "1"}' in html
    assert '{"label": "news", "pk": "1"}' in html
    assert 'hx-post="/admin/post/1/edit"' in html


def test_edit_form_renders_combobox(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/1/edit").text
    assert 'x-data=\'combobox("author", false, ' in html
    assert 'x-data=\'combobox("tags", true, ' in html
    assert 'hx-get="/admin/post/_lookup/author"' in html
    assert 'hx-target="next .combobox-options"' in html
    assert '"label": "ada@x.io"' in html
    assert ':disabled="selected.length > 0"' in html


def test_edit_success(factory: AppFactory, make_client: MakeClient) -> None:
    data = {"title": "Renamed", "status": "published", "author": "2", "tags": []}
    with make_client(build(factory)) as client:
        response = client.post("/admin/post/1/edit", data=data, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/post/1"
        detail = client.get("/admin/post/1").text
        related = client.get("/admin/post/_related/1/tags").text
    assert "Renamed" in detail
    assert 'href="/admin/user/2"' in detail
    assert "news" not in related


def test_edit_can_view_false_redirects_to_list(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        can_view = False
        can_edit = True

    data = {"title": "Renamed", "status": "draft", "author": "1"}
    with make_client(app) as client:
        response = client.post("/admin/post/1/edit", data=data, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/post/"


def test_on_save_hook_runs_before_commit(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        detail_columns = ("title", "body")

        async def on_save(
            self, request: Request, session: AsyncSession, obj: Post, *, created: bool
        ) -> None:
            if created:
                obj.body = "hooked"

    with make_client(app) as client:
        response = client.post("/admin/post/new", data=POST_DATA, follow_redirects=False)
        detail = client.get(response.headers["location"]).text
    assert "hooked" in detail


def test_can_create_false_403(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        can_create = False

    with make_client(app) as client:
        assert client.get("/admin/post/new").status_code == 403
        assert client.post("/admin/post/new", data=POST_DATA).status_code == 403
        listing = client.get("/admin/post/").text
    assert "/admin/post/new" not in listing


def test_can_edit_false_403(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        can_edit = False

    with make_client(app) as client:
        assert client.get("/admin/post/1/edit").status_code == 403
        assert client.post("/admin/post/1/edit", data=POST_DATA).status_code == 403
        detail = client.get("/admin/post/1").text
    assert "/admin/post/1/edit" not in detail


def test_edit_composite_pk(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        form = client.get("/admin/vote/2;1/edit")
        assert form.status_code == 200
        assert '{"label": "bob@x.io", "pk": "2"}' in form.text
        assert '{"label": "Hello", "pk": "1"}' in form.text
        response = client.post(
            "/admin/vote/2;1/edit",
            data={"value": "9", "user": "2", "post": "1"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/vote/2;1"
        detail = client.get("/admin/vote/2;1").text
    assert ">9<" in detail


def test_edit_not_found(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        assert client.get("/admin/post/999/edit").status_code == 404
