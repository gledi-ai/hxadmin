import re
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, Table
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import FormError, HxAdmin, ModelOperation, ModelView, define_audit_table
from tests.conftest import AppFactory, Base, Post, User
from tests.test_detail import seed

POST_IMPORT = "/admin/post/_import"
USER_IMPORT = "/admin/user/_import"


@pytest.fixture
def audit_table() -> Iterator[Table]:
    table = define_audit_table(Base.metadata)
    yield table
    Base.metadata.remove(table)


def build(factory: AppFactory, audit_table: Table) -> FastAPI:
    app = factory.app(seed=seed)

    def auth(request: Request) -> str:
        return request.headers.get("X-Actor", "operator")

    admin = HxAdmin(
        app, session=factory.get_session, auth=auth, audit_table=audit_table, audit_actor=str
    )

    @admin.register
    class UserView(ModelView[User]):
        model = User
        import_columns = ("email", "active")
        audit_fields = ("email", "active")

        def get_query(self, request: Request) -> Select[User]:
            stmt = super().get_query(request)
            return stmt.where(User.active.is_(True)) if request.headers.get("X-Scope") else stmt

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        import_columns = ("title", "author", "status", "body")
        audit_fields = ("title", "author_id")

        def is_operation_allowed(self, request: Request, operation: ModelOperation) -> bool:
            return operation != "create" or request.state.hxadmin_user != "reader"

        async def on_save(
            self, request: Request, session: AsyncSession, obj: Post, *, created: bool
        ) -> None:
            if obj.title == "Rejected":
                raise FormError("Title rejected by the save hook.", field="title")
            if obj.title == "Early commit":
                await session.commit()
            obj.title = obj.title.upper()

    return app


def preview(client: TestClient, base: str, data: bytes, **headers: str):
    return client.post(f"{base}/upload", files={"csv": ("records.csv", data)}, headers=headers)


def payload(html: str) -> str:
    match = re.search(r'type="hidden" name="csv" value="([^"]+)"', html)
    assert match is not None
    return match[1]


def confirm(client: TestClient, base: str, html: str, **headers: str):
    return client.post(
        f"{base}/confirm",
        files={"csv": (None, payload(html))},
        headers=headers,
        follow_redirects=False,
    )


def test_preview_and_commit_with_audit(factory: AppFactory, audit_table: Table) -> None:
    with TestClient(build(factory, audit_table)) as client:
        assert "Import CSV" in client.get("/admin/post/").text
        assert "Download template" in client.get(f"{POST_IMPORT}/upload").text
        template = client.get(f"{POST_IMPORT}/template")
        assert template.content.decode("utf-8-sig") == "title,author,status,body\r\n"
        assert "attachment" in template.headers["content-disposition"]

        response = preview(
            client, POST_IMPORT, b'author,title,body\r\n1,First,"a,b\r\nc"\r\n1,Second,\r\n'
        )
        assert response.status_code == 200
        assert "Import 2 records" in response.text
        assert "First" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "FIRST" not in client.get("/admin/post/").text
        assert client.get("/admin/post/2").status_code == 404

        result = confirm(client, POST_IMPORT, response.text)
        assert result.status_code == 303
        assert result.headers["location"] == "/admin/post/"
        assert "Imported 2 records." in client.get(result.headers["location"]).text
        assert "FIRST" in client.get("/admin/post/2").text
        assert "SECOND" in client.get("/admin/post/3").text
        history = client.get("/admin/post/_history/2").text
        assert '"FIRST"' in history
        assert "by operator" in history


def test_preview_reports_row_errors_and_limits(factory: AppFactory, audit_table: Table) -> None:
    with TestClient(build(factory, audit_table)) as client:
        invalid = preview(
            client, POST_IMPORT, b"title,author,status\nGood,1,invalid\nMissing,999,draft\nTwo,1\n"
        )
        assert invalid.status_code == 422
        assert "Unknown selection." in invalid.text
        assert "Expected 3 columns." in invalid.text
        assert "published" in invalid.text
        assert f'action="{POST_IMPORT}/confirm"' not in invalid.text
        assert client.get("/admin/post/2").status_code == 404
        for data, message in [
            (b"title,title,author", "duplicate columns"),
            (b"title,author,extra", "unknown columns"),
            (b"title", "Missing required columns"),
            (b'title,author\n"unclosed,1', "could not be read"),
            (b"title,author\n\xff", "UTF-8"),
            (b"title,author\n", "at least one record"),
            (b"title,author\n" + b"Post,1\n" * 501, "up to 500 records"),
            (b"x" * (1024 * 1024 + 4097), "1 MiB or smaller"),
        ]:
            response = preview(client, POST_IMPORT, data)
            assert response.status_code == 422
            assert message in response.text


def test_import_permissions_and_scope_are_checked_again(
    factory: AppFactory, audit_table: Table
) -> None:
    with TestClient(build(factory, audit_table)) as client:
        reader = {"X-Actor": "reader"}
        assert "Import CSV" not in client.get("/admin/post/", headers=reader).text
        for path in ("upload", "template"):
            assert client.get(f"{POST_IMPORT}/{path}", headers=reader).status_code == 403
        data = b"title,author\nFirst,1\nSecond,2\n"
        assert preview(client, POST_IMPORT, data, **reader).status_code == 403
        restricted = preview(client, POST_IMPORT, data, **{"X-Scope": "active"})
        assert restricted.status_code == 422
        assert "Unknown selection." in restricted.text
        accepted = preview(client, POST_IMPORT, data)
        assert confirm(client, POST_IMPORT, accepted.text, **reader).status_code == 403
        response = confirm(client, POST_IMPORT, accepted.text, **{"X-Scope": "active"})
        assert response.status_code == 422
        assert "Unknown selection." in response.text
        assert client.get("/admin/post/2").status_code == 404


def test_conflicts_and_save_hooks_roll_back_batch(factory: AppFactory, audit_table: Table) -> None:
    with TestClient(build(factory, audit_table)) as client:
        users = preview(
            client, USER_IMPORT, b"email,active\nnew@example.com,false\nada@x.io,true\n"
        )
        assert users.status_code == 200
        response = confirm(client, USER_IMPORT, users.text)
        assert response.status_code == 422
        assert "conflicts with existing data" in response.text
        assert client.get("/admin/user/3").status_code == 404

        posts = preview(client, POST_IMPORT, b"title,author\nFirst,1\nRejected,1\n")
        assert posts.status_code == 200
        response = confirm(client, POST_IMPORT, posts.text)
        assert response.status_code == 422
        assert "Title rejected by the save hook." in response.text
        assert client.get("/admin/post/2").status_code == 404

        accepted = preview(client, USER_IMPORT, b"email,active\nnew@example.com,false\n")
        assert confirm(client, USER_IMPORT, accepted.text).status_code == 303
        history = client.get("/admin/user/_history/3").text
        assert "new@example.com" in history
        assert "false" in history


def test_hook_cannot_commit_early(factory: AppFactory, audit_table: Table) -> None:
    with TestClient(build(factory, audit_table)) as client:
        posts = preview(client, POST_IMPORT, b"title,author\nFirst,1\nEarly commit,1\n")
        with pytest.raises(RuntimeError, match="Leave the commit of a CSV import"):
            confirm(client, POST_IMPORT, posts.text)
        assert client.get("/admin/post/2").status_code == 404


def test_import_configuration_rejects_invalid_columns() -> None:
    class MissingAuthor(ModelView[Post]):
        model = Post
        import_columns = ("title",)

    class ReadonlyColumn(ModelView[Post]):
        model = Post
        import_columns = ("title", "author", "id")

    class Collections(ModelView[Post]):
        model = Post
        import_columns = ("title", "author", "tags")

    with pytest.raises(ValueError, match="must include 'author'"):
        MissingAuthor()
    with pytest.raises(ValueError, match="'id' is not a writable create field"):
        ReadonlyColumn()
    with pytest.raises(ValueError, match="'tags' must be a writable many-to-one relationship"):
        Collections()
