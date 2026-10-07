from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Post, User, allow_all
from tests.test_detail import seed

type MakeClient = Callable[[FastAPI], TestClient]


def build(
    factory: AppFactory,
    *,
    register_users: bool = True,
    user_view: type[ModelView[User]] | None = None,
    editable: bool = True,
    exclude: tuple[str, ...] = (),
) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    if user_view is not None:
        admin.register(user_view)
    elif register_users:

        @admin.register
        class UserView(ModelView[User]):
            model = User
            searchable = ("email",)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        can_create = editable
        can_edit = editable
        form_exclude = exclude

    return app


def test_lookup_registered_target_searches_searchable(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/post/_lookup/author?q=ada")
    html = response.text
    assert response.status_code == 200
    assert 'pick("1", "ada@x.io")' in html
    assert "bob" not in html
    assert "<html" not in html


def test_lookup_registered_without_q_lists_first_20(
    factory: AppFactory, make_client: MakeClient
) -> None:
    async def many(session: AsyncSession) -> None:
        session.add_all([User(email=f"u{i:02d}@x.io") for i in range(25)])

    app = factory.app(seed=many)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

    with make_client(app) as client:
        html = client.get("/admin/post/_lookup/author?q=").text
    assert html.count('role="option"') == 20


def test_lookup_registered_without_searchable_filters_by_display(
    factory: AppFactory, make_client: MakeClient
) -> None:
    class Users(ModelView[User]):
        model = User

    with make_client(build(factory, user_view=Users)) as client:
        hit = client.get("/admin/post/_lookup/author?q=ADA").text
        miss = client.get("/admin/post/_lookup/author?q=zzzz").text
    assert "ada@x.io" in hit
    assert "bob" not in hit
    assert "No matches" in miss


def test_lookup_filtering_by_display_finds_rows_past_the_first_20(
    factory: AppFactory, make_client: MakeClient
) -> None:
    async def many(session: AsyncSession) -> None:
        session.add_all([User(email=f"u{i:02d}@x.io") for i in range(25)])

    app = factory.app(seed=many)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

    with make_client(app) as client:
        html = client.get("/admin/post/_lookup/author?q=u24").text
    assert "u24@x.io" in html


def test_lookup_unregistered_target_filters_by_str(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory, register_users=False)) as client:
        hit = client.get("/admin/post/_lookup/author?q=ada").text
        miss = client.get("/admin/post/_lookup/author?q=zzz").text
    assert "ada@x.io" in hit
    assert "bob" not in hit
    assert "No matches" in miss
    assert "zzz" in miss


def test_lookup_respects_target_get_query_and_is_accessible(
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

    with make_client(build(factory, user_view=ActiveUsers)) as client:
        html = client.get("/admin/post/_lookup/author?q=").text
    assert "ada@x.io" in html
    assert "bob" not in html
    with make_client(build(factory, user_view=Locked)) as client:
        assert client.get("/admin/post/_lookup/author?q=").status_code == 403


def test_lookup_unknown_or_non_relation_field_404(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        assert client.get("/admin/post/_lookup/title").status_code == 404
        assert client.get("/admin/post/_lookup/nope").status_code == 404


def test_lookup_requires_create_or_edit(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory, editable=False)) as client:
        assert client.get("/admin/post/_lookup/author").status_code == 403


def test_lookup_excluded_form_field_404(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory, exclude=("author",))) as client:
        assert client.get("/admin/post/_lookup/author").status_code == 404
