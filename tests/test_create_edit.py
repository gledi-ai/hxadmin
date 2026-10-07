import logging
import re
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, select
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import Account, AppFactory, Group, Post, Tag, User, Vote, allow_all
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]

POST_DATA = {"title": "New", "status": "draft", "author": "1", "tags": ["1"]}


def build(factory: AppFactory, *, user_view: type[ModelView[User]] | None = None) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    if user_view is not None:
        admin.register(user_view)
    else:

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
    assert 'step="any"' in html
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


def test_create_relation_pk_outside_target_scope_is_unknown(
    factory: AppFactory, make_client: MakeClient
) -> None:
    class ActiveUsers(ModelView[User]):
        model = User

        def get_query(self, request: Request) -> Select[User]:
            return select(User).where(User.active.is_(True))

    class Locked(ModelView[User]):
        model = User

        def is_accessible(self, request: Request) -> bool:
            return False

    for user_view in (ActiveUsers, Locked):
        with make_client(build(factory, user_view=user_view)) as client:
            saved = client.post("/admin/post/new", data={**POST_DATA, "author": "2"})
            invalid = client.post("/admin/post/new", data={**POST_DATA, "title": "", "author": "2"})
            listing = client.get("/admin/post/").text
        assert saved.status_code == 422
        assert "Unknown selection." in saved.text
        assert "bob@x.io" not in saved.text
        assert invalid.status_code == 422
        assert "bob@x.io" not in invalid.text
        assert "Showing 1\u20131 of 1" in listing


def test_create_relation_pk_inside_target_scope_is_saved(
    factory: AppFactory, make_client: MakeClient
) -> None:
    class ActiveUsers(ModelView[User]):
        model = User

        def get_query(self, request: Request) -> Select[User]:
            return select(User).where(User.active.is_(True))

    with make_client(build(factory, user_view=ActiveUsers)) as client:
        response = client.post("/admin/post/new", data=POST_DATA, follow_redirects=False)
    assert response.status_code == 303


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
    assert "#1" in html
    assert '{"label": "ada@x.io", "pk": "1"}' in html
    assert '{"label": "news", "pk": "1"}' in html
    assert 'hx-post="/admin/post/1/edit"' in html


def test_edit_form_partial(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/1/edit", headers={"HX-Request": "true"}).text
    assert "<html" not in html
    assert html.lstrip().startswith("<form")
    assert 'value="Hello"' in html


def test_edit_form_renders_combobox(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/1/edit").text
    assert 'x-data=\'combobox("author", false, ' in html
    assert 'x-data=\'combobox("tags", true, ' in html
    assert 'hx-get="/admin/post/_lookup/author"' in html
    assert 'hx-target="next .combobox-options"' in html
    assert '"label": "ada@x.io"' in html
    assert ':disabled="selected.length > 0"' in html
    assert (
        '<input type="hidden" :name="name" :value="selected.length ? selected[0].pk : \'\'">'
        in html
    )
    assert 'x-text="selected[0] && selected[0].label"' in html
    assert '@click="remove(selected[0].pk)"' in html


def test_edit_success(factory: AppFactory, make_client: MakeClient) -> None:
    data = {"title": "Renamed", "status": "published", "score": "0", "author": "2", "tags": []}
    with make_client(build(factory)) as client:
        response = client.post("/admin/post/1/edit", data=data, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/post/1"
        detail = client.get("/admin/post/1").text
        related = client.get("/admin/post/_related/1/tags").text
    assert "Renamed" in detail
    assert 'href="/admin/user/2"' in detail
    assert "news" not in related


def test_edit_htmx_success_sends_hx_redirect(factory: AppFactory, make_client: MakeClient) -> None:
    data = {"title": "Renamed", "status": "draft", "score": "0", "author": "1", "tags": ["1"]}
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/post/1/edit", data=data, headers={"HX-Request": "true"}, follow_redirects=False
        )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/admin/post/1"


def test_edit_validation_errors_rerender_422(factory: AppFactory, make_client: MakeClient) -> None:
    data = {"title": "", "status": "draft", "author": "1", "tags": ["1"]}
    with make_client(build(factory)) as client:
        full = client.post("/admin/post/1/edit", data=data)
        partial = client.post("/admin/post/1/edit", data=data, headers={"HX-Request": "true"})
        detail = client.get("/admin/post/1").text
    assert full.status_code == 422
    assert "This field is required." in full.text
    assert 'aria-invalid="true"' in full.text
    assert 'hx-post="/admin/post/1/edit"' in full.text
    assert '{"label": "ada@x.io", "pk": "1"}' in full.text
    assert "<html" in full.text
    assert partial.status_code == 422
    assert "<html" not in partial.text
    assert partial.text.lstrip().startswith("<form")
    assert "Hello" in detail


def test_edit_integrity_error_is_form_error(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/user/2/edit", data={"email": "ada@x.io", "active": ""})
        detail = client.get("/admin/user/2").text
    assert response.status_code == 422
    assert 'role="alert"' in response.text
    assert 'hx-post="/admin/user/2/edit"' in response.text
    assert "bob@x.io" in detail


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

    data = {"title": "Renamed", "status": "draft", "score": "0", "author": "1"}
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
        assert "#2;1" in form.text
        assert 'id="f-user_id"' not in form.text
        assert 'id="f-post_id"' not in form.text
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


def test_edit_unknown_relation_with_conflicting_column_is_422(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/user/1/edit", data={"email": "bob@x.io", "active": "on", "group": "999"}
        )
        detail = client.get("/admin/user/1").text
    assert response.status_code == 422
    assert "Unknown selection." in response.text
    assert "ada@x.io" in detail


def test_edit_ignores_identifying_relations(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        form = client.get("/admin/vote/2;1/edit").text
        assert 'name="user"' not in form
        assert 'name="post"' not in form
        response = client.post(
            "/admin/vote/2;1/edit", data={"value": "7", "user": "1"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/vote/2;1"
        assert client.get("/admin/vote/1;1").status_code == 404
        assert ">7<" in client.get("/admin/vote/2;1").text


def test_edit_empty_non_nullable_value_is_required_error(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/vote/2;1/edit", data={"value": ""})
        detail = client.get("/admin/vote/2;1").text
    assert response.status_code == 422
    assert "This field is required." in response.text
    assert ">5<" in detail


def test_create_empty_defaulted_column_uses_model_default(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/post/new", data={**POST_DATA, "score": ""}, follow_redirects=False
        )
        assert response.status_code == 303
        detail = client.get("/admin/post/2/edit").text
    assert 'name="score" value="0.0"' in detail


def _committing_app(factory: AppFactory) -> tuple[FastAPI, HxAdmin]:
    app = factory.app(seed=seed)

    async def committing_session() -> AsyncIterator[AsyncSession]:
        async with factory.sessionmaker() as session:
            try:
                yield session
            finally:
                await session.commit()

    return app, HxAdmin(app, session=committing_session, auth=allow_all)


def test_on_save_exception_rolls_back(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _committing_app(factory)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

        async def on_save(
            self, request: Request, session: AsyncSession, obj: Post, *, created: bool
        ) -> None:
            raise RuntimeError("boom")

    data = {"title": "Renamed", "status": "draft", "score": "0", "author": "1"}
    with make_client(app) as client:
        with pytest.raises(RuntimeError):
            client.post("/admin/post/1/edit", data=data)
        detail = client.get("/admin/post/1").text
    assert "Hello" in detail
    assert "Renamed" not in detail


def test_on_delete_exception_rolls_back(factory: AppFactory, make_client: MakeClient) -> None:
    app, admin = _committing_app(factory)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

        async def on_delete(self, request: Request, session: AsyncSession, obj: Post) -> None:
            obj.title = "half-deleted"
            raise RuntimeError("boom")

    with make_client(app) as client:
        with pytest.raises(RuntimeError):
            client.post("/admin/post/1/delete")
        detail = client.get("/admin/post/1").text
    assert "Hello" in detail


def test_inputs_are_36px_and_title_form_and_footer_share_one_left_column(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/new").text
    title_input = re.search(r'<input id="f-title"[^>]*class="([^"]*)"', html)
    assert title_input is not None
    assert "h-9" in title_input.group(1).split()
    columns = re.findall(r'<div class="([^"]*max-w-\[720px\][^"]*)"', html)
    assert len(columns) == 3
    for classes in columns:
        assert "mx-auto" not in classes.split()
    footer = html[html.index("sticky bottom-0") :]
    assert footer.index("max-w-[720px]") < footer.index("Cancel")


def test_selects_share_the_combobox_chevron(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/new").text
    select = html[html.index('<select name="status"') :]
    assert 'class="appearance-none pr-8 h-9 mt-1' in select[:200]
    assert '<path d="m6 9 6 6 6-6" />' in select[: select.index("</div>")]


def test_short_fields_share_a_row_and_long_ones_take_the_full_width(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/new").text
    by_field = {
        name: width
        for width, name in re.findall(
            r'data-field-width="(\w+)">\s*<div>\s*<label for="f-(\w+)"', html
        )
    }
    assert by_field == {
        "title": "full",
        "body": "full",
        "status": "half",
        "score": "half",
        "published_at": "half",
        "author": "half",
        "tags": "full",
    }


def build_accounts(factory: AppFactory) -> FastAPI:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class AccountView(ModelView[Account]):
        model = Account

    return app


def test_create_rejects_string_longer_than_column(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build_accounts(factory)) as client:
        response = client.post("/admin/account/new", data={"handle": "ninechars"})
    assert response.status_code == 422
    assert "at most 8 characters" in response.text


@pytest.mark.parametrize(
    ("column", "value", "limit"),
    [
        ("small", 32768, "32767"),
        ("medium", 2**31, "2147483647"),
        ("big", 2**63, "9223372036854775807"),
    ],
)
def test_create_rejects_integer_outside_column_range(
    factory: AppFactory, make_client: MakeClient, column: str, value: int, limit: str
) -> None:
    with make_client(build_accounts(factory)) as client:
        response = client.post("/admin/account/new", data={"handle": "ok", column: str(value)})
    assert response.status_code == 422
    assert f"less than or equal to {limit}" in response.text


def test_create_accepts_integers_within_column_range(
    factory: AppFactory, make_client: MakeClient
) -> None:
    data = {"handle": "ok", "small": "-32768", "medium": "2147483647", "big": str(2**31)}
    with make_client(build_accounts(factory)) as client:
        response = client.post("/admin/account/new", data=data, follow_redirects=False)
    assert response.status_code == 303


def test_database_rejecting_a_value_is_a_form_error(
    factory: AppFactory, make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

        async def on_save(
            self, request: Request, session: AsyncSession, obj: Post, *, created: bool
        ) -> None:
            raise DataError("INSERT ...", {}, Exception("value too long for type varchar(8)"))

    with make_client(app) as client, caplog.at_level(logging.WARNING, logger="hxadmin"):
        response = client.post("/admin/post/new", data=POST_DATA)
    assert response.status_code == 422
    assert "the database rejected a value" in response.text
    assert "varchar(8)" not in response.text
    assert "varchar(8)" in caplog.text


def test_integrity_error_hides_the_database_message(
    factory: AppFactory, make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    data = {"email": "ada@x.io", "active": "on"}
    with make_client(build(factory)) as client, caplog.at_level(logging.WARNING, logger="hxadmin"):
        response = client.post("/admin/user/new", data=data)
    assert response.status_code == 422
    assert "conflicts with existing data" in response.text
    assert "UNIQUE constraint failed" not in response.text
    assert "UNIQUE constraint failed" in caplog.text


def test_unknown_column_type_is_left_out_of_forms(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build_accounts(factory)) as client:
        html = client.get("/admin/account/new").text
    assert 'name="handle"' in html
    assert 'name="blob"' not in html


def test_unknown_column_type_cannot_be_a_form_field() -> None:
    class AccountView(ModelView[Account]):
        model = Account
        form_fields = ("handle", "blob")

    with pytest.raises(ValueError, match="'blob'"):
        AccountView()
