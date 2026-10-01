import re
from collections.abc import Callable
from typing import ClassVar

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Group, Post, Tag, User, Vote, allow_all
from tests.html import classes, tag


async def seed(session: AsyncSession) -> None:
    staff = Group(name="staff")
    ada = User(email="ada@x.io", group=staff)
    bob = User(email="bob@x.io", group=staff, active=False)
    tag = Tag(name="news")
    post = Post(title="Hello", author=ada, tags=[tag])
    session.add_all([ada, bob, post, Vote(user=bob, post=post, value=5)])


def build(factory: AppFactory, *, register_tags: bool = True) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class UserView(ModelView[User]):
        model = User
        list_columns = ("email", "active")

        def format_email(self, obj: User) -> str:
            return obj.email.upper()

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        detail_columns = ("title", "status", "published_at", "author", "tags")

    @admin.register
    class VoteView(ModelView[Vote]):
        model = Vote

    if register_tags:

        @admin.register
        class TagView(ModelView[Tag]):
            model = Tag

    return app


def test_full_page(factory: AppFactory, make_client: Callable[[FastAPI], TestClient]) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/1").text
    assert "<html" in html
    assert "<title>Hello" in html
    assert "<dt" in html
    assert "Title" in html
    assert "draft" in html
    assert "—" in html
    assert 'href="/admin/user/1">ada@x.io</a>' in html
    assert 'hx-get="/admin/post/_related/1/tags"' in html
    assert 'hx-trigger="intersect once"' in html
    assert "news" not in html


def test_partial_on_hx_request(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/1", headers={"HX-Request": "true"}).text
    assert "<html" not in html
    assert "<dl" in html


def test_formatter_applies_on_detail(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/1").text
    assert "ADA@X.IO" in html
    assert 'href="/admin/group/1">' in html
    assert 'hx-get="/admin/user/_related/1/posts"' in html


def test_composite_pk_detail(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/vote/2;1").text
    assert "Vote 2;1" in html
    assert ">5<" in html


def test_not_found(factory: AppFactory, make_client: Callable[[FastAPI], TestClient]) -> None:
    with make_client(build(factory)) as client:
        assert client.get("/admin/post/999").status_code == 404
        assert client.get("/admin/post/abc").status_code == 404
        assert client.get("/admin/vote/1").status_code == 404
        assert client.get("/admin/post/99999999999999999999").status_code == 404


def test_can_view_false_is_403(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User
        can_view = False

    with make_client(app) as client:
        assert client.get("/admin/user/1").status_code == 403


def test_related_registered_renders_table(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/group/1/", headers={"HX-Request": "true"}).text
        related = client.get("/admin/group/_related/1/users").text
    assert "<html" not in related
    assert "<table" in related
    assert "ADA@X.IO" in related
    assert "BOB@X.IO" in related
    assert 'href="/admin/user/2"' in related
    assert 'hx-get="/admin/group/_related/1/users?' in related
    assert "hx-push-url" not in related
    assert "Showing 1\u20132 of 2" in related
    assert html


def test_related_respects_list_params(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        related = client.get("/admin/group/_related/1/users?sort=email&dir=desc").text
    assert related.index("BOB@X.IO") < related.index("ADA@X.IO")


def test_related_unregistered_renders_plain_list(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory, register_tags=False)) as client:
        related = client.get("/admin/post/_related/1/tags").text
    assert "<table" not in related
    assert "<li" in related
    assert "Tag" in related


def test_related_scoped_by_target_view_query(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class UserView(ModelView[User]):
        model = User

        def get_query(self, request: Request) -> Select[tuple[User]]:
            return select(User).where(User.active.is_(True))

    with make_client(app) as client:
        related = client.get("/admin/group/_related/1/users").text
    assert "ada@x.io" in related
    assert "bob@x.io" not in related


def test_related_403_when_target_not_accessible(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class UserView(ModelView[User]):
        model = User

        def is_accessible(self, request: Request) -> bool:
            return False

    with make_client(app) as client:
        assert client.get("/admin/group/_related/1/users").status_code == 403


def test_related_rejects_non_collection(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        assert client.get("/admin/post/_related/1/author").status_code == 404
        assert client.get("/admin/post/_related/1/title").status_code == 404
        assert client.get("/admin/post/_related/999/tags").status_code == 404


def test_related_403_when_parent_can_view_false(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group
        can_view = False

    @admin.register
    class UserView(ModelView[User]):
        model = User

    with make_client(app) as client:
        assert client.get("/admin/group/_related/1/users").status_code == 403


def test_fk_column_hidden_by_default_when_relation_is_also_shown(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/1").text
    assert "Group id" not in html
    assert 'href="/admin/group/1">' in html


def test_explicit_detail_columns_still_show_the_fk_column(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

    @admin.register
    class UserView(ModelView[User]):
        model = User
        detail_columns = ("email", "group_id", "group")

    with make_client(app) as client:
        html = client.get("/admin/user/1").text
    assert "Group id" in html
    assert 'href="/admin/group/1">' in html


def header_badges(html: str) -> list[tuple[str, str]]:
    start = html.index("<h1")
    header = html[start : html.index("</div>", start)]
    badges = re.findall(r'<span class="[^"]*" data-tone="(\w+)">([^<]*)</span>', header)
    assert header.count("data-tone=") == len(badges)
    return badges


def test_detail_header_shows_one_badge_per_enum_field_with_its_tone(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    @admin.register
    class PostView(ModelView[Post]):
        model = Post
        badges: ClassVar = {"status": {"draft": "warning"}}

    with make_client(app) as client:
        html = client.get("/admin/post/1").text
        plain = client.get("/admin/user/1").text
    assert header_badges(html) == [("warning", "draft")]
    assert header_badges(plain) == []


def test_related_404_when_relation_excluded_from_detail_columns(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group
        detail_columns = ("name",)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    with make_client(app) as client:
        assert client.get("/admin/group/_related/1/users").status_code == 404


def test_header_stacks_and_fields_group_on_small_screens(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/user/1").text
    assert {"flex-col", "sm:flex-row"} <= classes(tag(html, "data-detail-header"))
    groups = re.findall(r'<dl class="([^"]*)" data-detail-group="(\w+)"', html)
    assert [name for _, name in groups] == ["columns", "relations"]
    for dl_class, _ in groups:
        assert {"grid-cols-1", "md:grid-cols-2"} <= set(dl_class.split())


def test_related_tabs_are_linked_to_their_panels(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/post/1").text
    tab = re.search(r'<button type="button" role="tab"[^>]*>', html, re.DOTALL)
    assert tab is not None
    assert 'id="related-tab-tags"' in tab.group(0)
    assert 'aria-controls="related-panel-tags"' in tab.group(0)
    assert 'aria-selected="true"' in tab.group(0)
    assert 'id="related-panel-tags" aria-labelledby="related-tab-tags"' in html


def test_text_and_json_detail_values_span_both_columns(
    factory: AppFactory, make_client: Callable[[FastAPI], TestClient]
) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class PostView(ModelView[Post]):
        model = Post

    with make_client(app) as client:
        html = client.get("/admin/post/1").text
    widths = dict(re.findall(r'data-field="(\w+)" data-field-width="(\w+)"', html))
    assert widths["body"] == "full"
    assert widths["status"] == "half"
    assert widths["title"] == "half"
