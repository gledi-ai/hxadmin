import re
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import FormError, HxAdmin, ModelOperation, ModelView, define_audit_table
from tests.conftest import AppFactory, Base, Post, User, allow_all
from tests.html import tag

ADD_POST = "/admin/user/_inline/posts/new"
EDIT_USER = "/admin/user/1/edit"
HX = {"HX-Request": "true"}


@pytest.fixture
def inline_app(factory: AppFactory) -> Iterator[FastAPI]:
    async def seed(session: AsyncSession) -> None:
        ada = User(email="ada@example.com")
        bob = User(email="bob@example.com")
        session.add_all([ada, bob])
        await session.flush()
        session.add_all(
            [
                Post(title="Ada's first post", author=ada),
                Post(title="Hidden post", author=ada),
                Post(title="Bob's post", author=bob),
            ]
        )

    table = define_audit_table(Base.metadata)
    app = factory.app(seed=seed)
    admin = HxAdmin(
        app,
        session=factory.get_session,
        auth=allow_all,
        audit_table=table,
        audit_actor=lambda user: user["name"],
    )

    @admin.register
    class UserView(ModelView[User]):
        model = User
        form_fields = ("email", "posts")
        form_inlines = ("posts",)
        audit_fields = ("email",)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        form_fields = ("title", "score", "published_at", "tags", "author_id", "author")
        audit_fields = ("title", "author_id")

        def is_operation_allowed(self, request: Request, operation: ModelOperation) -> bool:
            return request.headers.get("X-Deny-Child") != operation

        def get_query(self, request: Request) -> Select[Post]:
            return super().get_query(request).where(Post.title != "Hidden post")

        async def on_save(
            self, request: Request, session: AsyncSession, obj: Post, *, created: bool
        ) -> None:
            if obj.title == "Rejected":
                raise FormError("Pick another title.", field="title")
            if created:
                obj.title = f"{obj.title} by {obj.author.email}"

    try:
        yield app
    finally:
        Base.metadata.remove(table)


def marker(html: str, value: str) -> str:
    match = re.search(r'name="(_hx_inline\.[\w.]+)" value="' + re.escape(value) + r'"', html)
    assert match is not None
    return match[1]


def test_inline_create_and_edit_share_the_parent_save(inline_app: FastAPI) -> None:
    with TestClient(inline_app) as client:
        form = client.get("/admin/user/new").text
        assert f'hx-get="{ADD_POST}"' in form
        assert 'hx-target="#inline-drafts-0"' in form
        assert "Save and add another user" in form
        assert 'name="posts"' not in form
        row = client.get(ADD_POST, headers=HX)
        assert row.headers["Cache-Control"] == "no-store"
        first = row.text
        assert "Discard draft" in first
        assert "x-init=" in first
        second = client.get(ADD_POST, headers=HX).text
        a, b = marker(first, "new"), marker(second, "new")
        assert a != b
        assert f'name="{a}.author_id"' not in first
        assert f'name="{a}.author"' not in first
        assert f'name="{a}.published_at"' in first
        assert f'id="f-{a}.tags"' in first

        response = client.post(
            "/admin/user/new",
            headers=HX,
            data={
                "email": "new@example.com",
                a: "new",
                f"{a}.title": "First",
                f"{a}.author_id": "2",
                b: "new",
                f"{b}.title": "Second",
            },
        )
        assert response.headers["HX-Redirect"] == "/admin/user/3"
        assert "First by new@example.com" in client.get("/admin/post/4").text
        assert "Second by new@example.com" in client.get("/admin/post/5").text
        assert "First by new@example.com" in client.get("/admin/post/_history/4").text

        form = client.get("/admin/user/3/edit").text
        assert "Save user" in form
        assert "Save and add another" not in form
        existing = marker(form, "edit:4")
        assert " disabled" in tag(form, 'x-show="editing" :disabled="!editing"')
        response = client.post(
            "/admin/user/3/edit",
            data={
                "email": "updated@example.com",
                existing: "edit:4",
                f"{existing}.title": "Edited",
                f"{existing}.score": "0",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "Edited" in client.get("/admin/post/4").text
        assert "Second by new@example.com" in client.get("/admin/post/5").text
        assert "updated@example.com" in client.get("/admin/user/_history/3").text
        assert "Edited" in client.get("/admin/post/_history/4").text


def test_invalid_inline_preserves_rows_and_rolls_back_prior_writes(inline_app: FastAPI) -> None:
    with TestClient(inline_app) as client:
        existing = marker(client.get(EDIT_USER).text, "edit:1")
        new = marker(client.get(ADD_POST).text, "new")
        data = {
            "email": "changed@example.com",
            existing: "edit:1",
            f"{existing}.title": "Do not persist",
            f"{existing}.score": "0",
            new: "new",
            f"{new}.title": "",
        }
        for title, message in (
            ("", "This field is required."),
            ("Rejected", "Pick another title."),
        ):
            data[f"{new}.title"] = title
            failed = client.post(EDIT_USER, headers=HX, data=data)
            assert failed.status_code == 422
            assert failed.text.index(f'name="{new}"') < failed.text.index(f'name="{existing}"')
            assert f'name="{new}.title"' in failed.text
            assert f'value="{title}"' in tag(failed.text, f'name="{new}.title"')
            assert 'aria-invalid="true"' in tag(failed.text, f'name="{new}.title"')
            assert message in failed.text
            assert "Do not persist" in failed.text
            assert "changed@example.com" in failed.text
            assert "changed@example.com" not in client.get("/admin/user/1").text
            assert "Do not persist" not in client.get("/admin/post/1").text
            assert "Do not persist" not in client.get("/admin/post/_history/1").text
            assert client.get("/admin/post/4").status_code == 404


def test_inline_rechecks_child_scope_and_permissions_on_submit(inline_app: FastAPI) -> None:
    with TestClient(inline_app) as client:
        form = client.get(EDIT_USER).text
        assert "Hidden post" not in form
        assert "Bob&#39;s post" not in form
        existing = marker(form, "edit:1")
        data = {"email": "changed@example.com", f"{existing}.title": "Changed"}
        for unrelated in ("edit:2", "edit:3"):
            assert client.post(EDIT_USER, data={**data, existing: unrelated}).status_code == 404
        assert (
            client.post(
                EDIT_USER, headers={"X-Deny-Child": "edit"}, data={**data, existing: "edit:1"}
            ).status_code
            == 403
        )
        assert client.get(ADD_POST, headers={"X-Deny-Child": "create"}).status_code == 403
        assert (
            client.post(
                EDIT_USER, headers={"X-Deny-Child": "create"}, data={**data, existing: "new"}
            ).status_code
            == 403
        )
        assert "changed@example.com" not in client.get("/admin/user/1").text
