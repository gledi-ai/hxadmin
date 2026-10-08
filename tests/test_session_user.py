"""An `auth` returning a row of the request session survives hxadmin's rollbacks and refreshes."""

from collections.abc import AsyncIterator, Callable, Sequence
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from hxadmin import ActionResult, FormError, HxAdmin, ModelView, action
from tests.conftest import AppFactory, Post, User

HTMX = {"HX-Request": "true"}


async def seed(session: AsyncSession) -> None:
    admin_user = User(email="admin@example.com")
    author = User(email="author@example.com")
    session.add_all([admin_user, Post(title="Hello", author=author)])


class PostView(ModelView[Post]):
    model = Post

    def is_action_allowed(self, request: Request, name: str) -> bool:
        return request.state.hxadmin_user.active

    async def on_save(
        self, request: Request, session: AsyncSession, obj: Post, *, created: bool
    ) -> None:
        raise FormError("Rejected.")

    @action("touch")
    async def touch(self, request: Request, session: AsyncSession, obj: Post) -> ActionResult:
        obj.score += 1
        return ActionResult.message("Touched.")

    @action("refuse")
    async def refuse(self, request: Request, session: AsyncSession, obj: Post) -> ActionResult:
        raise HTTPException(409, "Refused.")

    @action("bump", bulk=True)
    async def bump(
        self, request: Request, session: AsyncSession, objs: Sequence[Post]
    ) -> ActionResult:
        return ActionResult.message("Bumped.")


class UserView(ModelView[User]):
    model = User


@pytest.fixture(params=[False, True], ids=["keep-on-commit", "expire-on-commit"])
def client(
    request: pytest.FixtureRequest,
    factory: AppFactory,
    make_client: Callable[[FastAPI], TestClient],
) -> TestClient:
    sessionmaker = async_sessionmaker(factory.engine, expire_on_commit=request.param)

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    async def current_user(session: Annotated[AsyncSession, Depends(get_session)]) -> User:
        user = await session.scalar(select(User).where(User.email == "admin@example.com"))
        assert user is not None
        return user

    app = factory.app(seed)
    admin = HxAdmin(app, session=get_session, auth=current_user)
    admin.register(PostView)
    admin.register(UserView)
    return make_client(app)


def test_htmx_row_action_rerenders_detail_with_user_hooks(client: TestClient) -> None:
    with client:
        response = client.post("/admin/post/1/action/touch", headers=HTMX)
    assert response.status_code == 200
    assert "Touched." in response.headers["hx-trigger"]


def test_htmx_bulk_action_rerenders_list_with_user_hooks(client: TestClient) -> None:
    with client:
        response = client.post("/admin/post/action/bump", data={"pks": ["1"]}, headers=HTMX)
    assert response.status_code == 200
    assert "Bumped." in response.headers["hx-trigger"]


def test_action_http_exception_renders_error_page(client: TestClient) -> None:
    with client:
        response = client.post("/admin/post/1/action/refuse")
    assert response.status_code == 409
    assert "Refused." in response.text
    assert "admin@example.com" in response.text


def test_rejected_save_rerenders_form_in_shell(client: TestClient) -> None:
    with client:
        response = client.post(
            "/admin/post/1/edit",
            data={"title": "Changed", "body": "", "status": "draft", "score": "0", "author": "2"},
        )
    assert response.status_code == 422
    assert "Rejected." in response.text
    assert "admin@example.com" in response.text


def test_refused_delete_renders_error_page(client: TestClient) -> None:
    with client:
        response = client.post("/admin/user/2/delete")
    assert response.status_code == 409
    assert "admin@example.com" in response.text
