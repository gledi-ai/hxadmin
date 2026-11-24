from collections.abc import Iterator, Sequence

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, Select, Table, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import ActionResult, HxAdmin, ModelView, action, define_audit_table
from tests.conftest import AppFactory, Base, Post, PostStatus
from tests.test_detail import seed

POST_DATA = {"title": "New", "status": "draft", "author": "1", "score": "0"}


@pytest.fixture
def audit_table() -> Iterator[Table]:
    table = define_audit_table(Base.metadata)
    yield table
    Base.metadata.remove(table)


def build(factory: AppFactory, audit_table: Table) -> FastAPI:
    app = factory.app(seed=seed)

    def auth(request: Request) -> str:
        return request.headers.get("X-Actor", "17")

    admin = HxAdmin(
        app, session=factory.get_session, auth=auth, audit_table=audit_table, audit_actor=str
    )

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        audit_fields = ("title", "status", "author_id")

        def is_history_allowed(self, request: Request) -> bool:
            return request.headers.get("X-Actor") != "no-history"

        def get_query(self, request: Request) -> Select[Post]:
            stmt = super().get_query(request)
            return stmt.where(Post.id != 2) if request.headers.get("X-Actor") == "scoped" else stmt

        async def on_save(
            self, request: Request, session: AsyncSession, obj: Post, *, created: bool
        ) -> None:
            obj.title = obj.title.strip()

        @action("rename", label="Rename post", audit=True)
        async def rename(self, request: Request, session: AsyncSession, obj: Post) -> ActionResult:
            obj.title = "Renamed"
            return ActionResult.message("Renamed")

        @action("publish", bulk=True, audit=True)
        async def publish(
            self, request: Request, session: AsyncSession, objs: Sequence[Post]
        ) -> ActionResult:
            for obj in objs:
                obj.status = PostStatus.published
            return ActionResult.message("Published")

        @action("early_commit", audit=True)
        async def early_commit(
            self, request: Request, session: AsyncSession, obj: Post
        ) -> ActionResult:
            obj.title = "Premature change"
            await session.flush()
            await session.commit()
            return ActionResult.message("Committed")

    return app


def test_crud_history_and_record_scope(factory: AppFactory, audit_table: Table) -> None:
    path = "/admin/post/_history/2"
    with TestClient(build(factory, audit_table)) as client:
        assert "No changes recorded" in client.get("/admin/post/_history/1").text
        response = client.post("/admin/post/new", data=POST_DATA, follow_redirects=False)
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/admin/post/2"
        assert f'hx-get="{path}"' in client.get("/admin/post/2").text
        assert (
            f'hx-get="{path}"'
            not in client.get("/admin/post/2", headers={"X-Actor": "no-history"}).text
        )
        assert client.get(path, headers={"X-Actor": "no-history"}).status_code == 403
        assert client.get(path, headers={"X-Actor": "scoped"}).status_code == 404

        edited = {**POST_DATA, "title": "  Updated  ", "status": "published"}
        for _ in range(2):
            response = client.post("/admin/post/2/edit", data=edited, follow_redirects=False)
            assert response.status_code == status.HTTP_303_SEE_OTHER
        assert client.post("/admin/post/1/delete", follow_redirects=False).status_code == 409

        history = client.get("/admin/post/_history/02")
        assert history.status_code == status.HTTP_200_OK
        assert '<del>"New"</del>' in history.text
        assert '<span>"Updated"</span>' in history.text
        assert "by 17" in history.text
        assert history.text.index("<strong>Updated</strong>") < history.text.index(
            "<strong>Created</strong>"
        )
        assert client.post("/admin/post/2/delete", follow_redirects=False).status_code == 303
        assert client.get(path).status_code == 404

        async def inspect_entries() -> None:
            async with factory.sessionmaker() as session:
                result = await session.execute(select(audit_table).order_by(audit_table.c.id))
                entries = result.mappings().all()
            assert [entry.operation for entry in entries] == ["create", "update", "delete"]
            assert {entry.record_key for entry in entries} == {"2"}
            assert entries[0].changes["author_id"] == {"before": None, "after": 1}
            assert entries[1].changes == {
                "title": {"before": "New", "after": "Updated"},
                "status": {"before": "draft", "after": "published"},
            }
            assert entries[2].changes["title"] == {"before": "Updated", "after": None}

        assert client.portal is not None
        client.portal.call(inspect_entries)

        assert (
            client.post("/admin/post/new", data=POST_DATA, follow_redirects=False).status_code
            == 303
        )
        history = client.get(path).text
        assert "<strong>Created</strong>" in history
        assert "<strong>Updated</strong>" not in history


def test_audit_insert_failure_rolls_back_edit(factory: AppFactory, audit_table: Table) -> None:
    audit_table.append_constraint(CheckConstraint("actor_id <> 'reject'"))
    with TestClient(build(factory, audit_table)) as client:
        response = client.post(
            "/admin/post/1/edit",
            data=POST_DATA,
            headers={"X-Actor": "reject"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "conflicts with existing data" in response.text
        assert "<title>Hello" in client.get("/admin/post/1").text
        assert "No changes recorded" in client.get("/admin/post/_history/1").text


def test_history_paginates_without_repeating_entries(
    factory: AppFactory, audit_table: Table
) -> None:
    with TestClient(build(factory, audit_table)) as client:
        for number in range(26):
            response = client.post(
                "/admin/post/1/edit",
                data={**POST_DATA, "title": f"Title {number}"},
                follow_redirects=False,
            )
            assert response.status_code == status.HTTP_303_SEE_OTHER

        newest = client.get("/admin/post/_history/1").text
        assert newest.count("<strong>Updated</strong>") == 25
        assert 'href="/admin/post/_history/1?before=2"' in newest
        oldest = client.get("/admin/post/_history/1?before=2").text
        assert oldest.count("<strong>Updated</strong>") == 1
        assert '<span>"Title 0"</span>' in oldest
        assert "Load older changes" not in oldest


def test_audited_row_and_bulk_actions_only_record_changed_targets(
    factory: AppFactory, audit_table: Table
) -> None:
    with TestClient(build(factory, audit_table)) as client:
        for _ in range(2):
            assert (
                client.post("/admin/post/1/action/rename", follow_redirects=False).status_code
                == 303
            )
        assert (
            client.post("/admin/post/new", data=POST_DATA, follow_redirects=False).status_code
            == 303
        )
        response = client.post(
            "/admin/post/action/publish", data={"pks": ["1", "2", "999"]}, follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        for key in (1, 2):
            history = client.get(f"/admin/post/_history/{key}").text
            assert "<strong>Publish</strong>" in history
            assert '<del>"draft"</del>' in history
            assert '<span>"published"</span>' in history
            assert history.count("<strong>Rename post</strong>") == (1 if key == 1 else 0)


def test_audited_action_rejects_early_commit_and_rolls_back(
    factory: AppFactory, audit_table: Table
) -> None:
    with TestClient(build(factory, audit_table)) as client:
        response = client.post("/admin/post/1/action/early_commit", headers={"HX-Request": "true"})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "<title>Hello" in client.get("/admin/post/1").text
        assert "No changes recorded" in client.get("/admin/post/_history/1").text
