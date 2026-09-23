import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Post, PostStatus, User, allow_all

type MakeClient = Callable[[FastAPI], TestClient]

BADGE = re.compile(r'<span class="[^"]*" data-tone="(\w+)">([^<]*)</span>')


async def seed(session: AsyncSession) -> None:
    ada = User(email="ada@x.io", active=True)
    bob = User(email="bob@x.io", active=False)
    session.add_all(
        [
            ada,
            bob,
            Post(title="Draft", author=ada, status=PostStatus.draft),
            Post(title="Live", author=bob, status=PostStatus.published),
        ]
    )


def make_view(model: type[Any], badges: dict[str, dict[str, str]]) -> type[ModelView[Any]]:
    return type("BadgeView", (ModelView,), {"model": model, "badges": badges})


@pytest.mark.parametrize(
    ("model", "badges", "message"),
    [
        (Post, {"nope": {}}, "cannot declare badges for 'nope'"),
        (Post, {"title": {"x": "accent"}}, "cannot declare badges for 'title'"),
        (Post, {"author": {}}, "cannot declare badges for 'author'"),
        (Post, {"status": {"draft": "purple"}}, "unknown badge tone 'purple'"),
        (Post, {"status": {"Draft": "accent"}}, "'Draft' is not a value of 'status'"),
        (User, {"active": {"yes": "success"}}, "'yes' is not a value of 'active'"),
    ],
)
def test_badges_are_validated_at_registration(
    model: type[Any], badges: dict[str, dict[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        make_view(model, badges)()


def test_valid_badges_are_accepted() -> None:
    make_view(Post, {"status": {"draft": "warning", "published": "success"}})()
    make_view(User, {"active": {"true": "success", "false": "neutral"}})()


def build(factory: AppFactory, post_badges: dict[str, Any], user_badges: dict[str, Any]) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    class UserView(ModelView[User]):
        model = User
        list_columns = ("email", "active")
        badges = user_badges

    class PostView(ModelView[Post]):
        model = Post
        list_columns = ("title", "status")
        badges = post_badges

    admin.register(UserView)
    admin.register(PostView)
    return app


def table(html: str) -> str:
    return html[html.index("<table") : html.index("</table>")]


def test_enum_cells_use_the_declared_tone_and_default_to_neutral(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = build(factory, {"status": {"published": "success"}}, {})
    with make_client(app) as client:
        html = client.get("/admin/post/").text
    assert sorted(BADGE.findall(table(html))) == [("neutral", "draft"), ("success", "published")]


def test_bools_render_as_icons_unless_declared(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = build(factory, {}, {})
    with make_client(app) as client:
        html = client.get("/admin/user/").text
    assert BADGE.findall(table(html)) == []
    assert 'aria-label="Yes"' in table(html)
    assert 'aria-label="No"' in table(html)


def test_declared_bools_render_as_yes_no_badges(
    factory: AppFactory, make_client: MakeClient
) -> None:
    app = build(factory, {}, {"active": {"true": "success"}})
    with make_client(app) as client:
        html = client.get("/admin/user/").text
    assert sorted(BADGE.findall(table(html))) == [("neutral", "No"), ("success", "Yes")]
