import datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import QueryParams

from hxadmin.fields import Field, derive_fields
from hxadmin.filters import (
    Chip,
    FilterValue,
    apply_filters,
    filter_chips,
    parse_filters,
    resolve_filters,
)
from hxadmin.views import ModelView
from tests.conftest import Group, Post, PostStatus, User


class PostView(ModelView[Post]):
    model = Post
    list_filters = ("status", "score", "published_at", "title", "author")


class UserView(ModelView[User]):
    model = User
    list_filters = ("active", "group", "email")


def parse(view: ModelView[Any], query: str) -> tuple[FilterValue, ...]:
    return parse_filters(view.filters, QueryParams(query))


async def seed(session: AsyncSession) -> None:
    staff = Group(name="staff")
    ops = Group(name="ops")
    ada = User(email="ada@x.io", group=staff)
    bob = User(email="bob@x.io", active=False, group=ops)
    session.add_all(
        [
            Post(
                title="Alpha",
                status=PostStatus.published,
                score=1.0,
                published_at=datetime.datetime.fromisoformat("2026-01-01T09:00"),
                author=ada,
            ),
            Post(title="Beta", score=2.5, author=bob),
            Post(
                title="Gamma 100%",
                status=PostStatus.published,
                score=4.0,
                published_at=datetime.datetime.fromisoformat("2026-03-01T09:00"),
                author=bob,
            ),
            User(email="cy@y.io"),
        ]
    )
    await session.commit()


def test_filter_kinds_follow_field_kinds() -> None:
    resolved = {f.name: (f.kind, f.nullable, f.input_type) for f in PostView().filters}
    assert resolved == {
        "status": ("choice", False, "text"),
        "score": ("range", False, "number"),
        "published_at": ("range", True, "datetime-local"),
        "title": ("text", False, "text"),
        "author": ("relation", False, "text"),
    }
    status = PostView().filters[0]
    assert status.key == "f.status"
    assert status.choices == (("draft", "draft"), ("published", "published"))
    users = {f.name: f for f in UserView().filters}
    assert users["active"].choices == (("true", "Yes"), ("false", "No"))
    assert users["group"].nullable


@pytest.mark.parametrize(
    ("names", "message"),
    [(("nope",), "unknown field 'nope'"), (("tags",), "to-many relation 'tags'")],
)
def test_unfilterable_names_are_rejected(names: tuple[str, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_filters("PostView", derive_fields(Post), names)


def test_json_columns_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot filter on json column 'data'"):
        resolve_filters("DocView", {"data": Field("data", "json")}, ("data",))


def test_parse_keeps_valid_values_in_declaration_order() -> None:
    query = (
        "f.author=1&f.status=published&f.status=bogus&f.status=published"
        "&f.score.min=1.5&f.score.max=x&f.title=%20hi%20&f.published_at.min=2026-01-02T03:04"
    )
    assert parse(PostView(), query) == (
        FilterValue("status", ("published",)),
        FilterValue("score", min="1.5"),
        FilterValue("published_at", min="2026-01-02T03:04"),
        FilterValue("title", ("hi",)),
        FilterValue("author", ("1",)),
    )


@pytest.mark.parametrize(
    "query",
    [
        "f.score.min=nan",
        "f.score.max=inf",
        "f.author=x",
        "f.author=1;2",
        "f.author=99999999999999999999",
        "f.status.empty=1",
        "f.title=%20%20",
        "f.published_at.max=yesterday",
        "status=draft",
    ],
)
def test_parse_drops_invalid_values(query: str) -> None:
    assert parse(PostView(), query) == ()


def test_parse_drops_out_of_range_integer_bounds() -> None:
    filters = resolve_filters("PostView", derive_fields(Post), ("id",))
    query = "f.id.min=99999999999999999999&f.id.max=-99999999999999999999"
    assert parse_filters(filters, QueryParams(query)) == ()


def test_parse_bool_and_empty() -> None:
    assert parse(UserView(), "f.active=true&f.group.empty=1&f.email=&f.active.empty=1") == (
        FilterValue("active", ("true",)),
        FilterValue("group", empty=True),
    )
    assert parse(UserView(), "f.group.empty=yes") == ()


def test_pairs_round_trip_through_parse() -> None:
    value = FilterValue("published_at", min="2026-01-01", max="2026-02-01", empty=True)
    assert value.pairs() == [
        ("f.published_at.min", "2026-01-01"),
        ("f.published_at.max", "2026-02-01"),
        ("f.published_at.empty", "1"),
    ]
    assert parse_filters(PostView().filters, QueryParams(value.pairs())) == (value,)


async def matching(session: AsyncSession, view: ModelView[Any], query: str) -> list[str]:
    stmt = apply_filters(select(view.model), view.model, view.filters, parse(view, query))
    return [str(row) for row in (await session.scalars(stmt.order_by(view.model.id))).all()]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("f.status=published", ["Alpha", "Gamma 100%"]),
        ("f.status=draft&f.status=published", ["Alpha", "Beta", "Gamma 100%"]),
        ("f.score.min=1&f.score.max=2.5", ["Alpha", "Beta"]),
        ("f.published_at.min=2026-02-01", ["Gamma 100%"]),
        ("f.published_at.max=2026-02-01T00:00&f.published_at.empty=1", ["Alpha", "Beta"]),
        ("f.published_at.empty=1", ["Beta"]),
        ("f.title=AL", ["Alpha"]),
        ("f.title=%25", ["Gamma 100%"]),
        ("f.author=2", ["Beta", "Gamma 100%"]),
        ("f.author=2&f.status=published", ["Gamma 100%"]),
        ("", ["Alpha", "Beta", "Gamma 100%"]),
    ],
)
async def test_post_filters_narrow_rows(
    session: AsyncSession, query: str, expected: list[str]
) -> None:
    await seed(session)
    assert await matching(session, PostView(), query) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("f.active=false", ["bob@x.io"]),
        ("f.active=true&f.active=false", ["ada@x.io", "bob@x.io", "cy@y.io"]),
        ("f.group=1&f.group.empty=1", ["ada@x.io", "cy@y.io"]),
        ("f.email=Y.IO", ["cy@y.io"]),
    ],
)
async def test_user_filters_narrow_rows(
    session: AsyncSession, query: str, expected: list[str]
) -> None:
    await seed(session)
    assert await matching(session, UserView(), query) == expected


def test_chips_label_every_active_value() -> None:
    view = PostView()
    values = parse(
        view,
        "f.status=published&f.score.min=1&f.score.max=2&f.published_at.empty=1&f.title=hi"
        "&f.author=2",
    )
    assert filter_chips(view.filters, values, {"author": [("2", "bob@x.io")]}) == [
        Chip("Status: published", "f.status", "published"),
        Chip("Score ≥ 1", "f.score.min", None),
        Chip("Score ≤ 2", "f.score.max", None),
        Chip("Published at: empty", "f.published_at.empty", "1"),
        Chip("Title contains “hi”", "f.title", None),
        Chip("Author: bob@x.io", "f.author", "2"),
    ]
