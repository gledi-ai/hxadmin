import datetime
import decimal
import uuid
from typing import Any

import pytest
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import QueryParams
from starlette.requests import Request

from hxadmin import HxAdmin
from hxadmin.fields import Field, RelationField, derive_fields
from hxadmin.filters import (
    FilterValue,
    apply_filters,
    parse_filters,
    relation_labels,
    resolve_filters,
)
from hxadmin.views import ModelView
from tests.conftest import AppFactory, Group, Post, PostStatus, Reading, User, allow_all


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
        resolve_filters("PostView", Post, derive_fields(Post), names)


def test_reverse_one_to_one_relations_are_rejected() -> None:
    passport = RelationField("passport", "Passport", User, multiple=False)
    with pytest.raises(ValueError, match="non-many-to-one relation 'passport'"):
        resolve_filters("PersonView", User, {"passport": passport}, ("passport",))


def test_json_columns_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot filter on json column 'data'"):
        resolve_filters("DocView", Post, {"data": Field("data", "json")}, ("data",))


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
    filters = resolve_filters("PostView", Post, derive_fields(Post), ("id",))
    query = "f.id.min=99999999999999999999&f.id.max=-99999999999999999999"
    assert parse_filters(filters, QueryParams(query)) == ()


@pytest.mark.parametrize(
    ("query", "bound"),
    [
        ("f.taken_at.min=2026-02-01", "2026-02-01T00:00"),
        ("f.taken_at.min=2026-02-01T10:00:30", "2026-02-01T10:00:30"),
        ("f.taken_at.min=2026-02-01T12:00%2B02:00", "2026-02-01T10:00"),
        ("f.day.min=20260201", "2026-02-01"),
        ("f.at.min=10:00:00", "10:00"),
        ("f.count.min=1_000", "1000"),
        ("f.count.min=%2B7", "7"),
        ("f.amount.min=1E%2B2", "100"),
        ("f.amount.min=1.50", "1.50"),
    ],
)
def test_parse_writes_bounds_as_the_inputs_do(query: str, bound: str) -> None:
    (value,) = parse(ReadingView(), query)
    assert value.min == bound


def test_parse_writes_float_bounds_plainly() -> None:
    assert parse(PostView(), "f.score.min=1_000&f.score.max=2.50") == (
        FilterValue("score", min="1000", max="2.5"),
    )


def test_parse_bool_and_empty() -> None:
    assert parse(UserView(), "f.active=true&f.group.empty=1&f.email=&f.active.empty=1") == (
        FilterValue("active", ("true",)),
        FilterValue("group", empty=True),
    )
    assert parse(UserView(), "f.group.empty=yes") == ()


def test_pairs_round_trip_through_parse() -> None:
    value = FilterValue("published_at", min="2026-01-01T00:00", max="2026-02-01T10:30", empty=True)
    assert value.pairs() == [
        ("f.published_at.min", "2026-01-01T00:00"),
        ("f.published_at.max", "2026-02-01T10:30"),
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


class ReadingView(ModelView[Reading]):
    model = Reading
    list_filters = ("count", "amount", "day", "at", "taken_at", "synced_at", "ref")


def postgres_sql(query: str) -> str:
    view = ReadingView()
    stmt = apply_filters(select(Reading.id), Reading, view.filters, parse(view, query))
    return str(stmt.compile(dialect=asyncpg.dialect()))


def test_bounds_bind_types_wide_enough_for_any_value() -> None:
    sql = postgres_sql("f.count.max=3000000000&f.amount.min=100000000")
    assert "readings.count <= $1::BIGINT" in sql
    assert "readings.amount >= $2::NUMERIC" in sql
    assert "NUMERIC(10, 2)" not in sql


@pytest.mark.parametrize(
    ("query", "kept"),
    [
        ("f.amount.max=1e131071", True),
        ("f.amount.max=1e131072", False),
        ("f.amount.min=1e-16383", True),
        ("f.amount.min=1e-16384", False),
        ("f.amount.min=1e999999", False),
        ("f.amount.min=1.2.3", False),
        ("f.at.min=10:00%2B02:00", False),
        ("f.at.min=10:00", True),
    ],
)
def test_bounds_no_database_accepts_are_dropped(query: str, kept: bool) -> None:
    assert bool(parse(ReadingView(), query)) is kept


async def seed_readings(session: AsyncSession) -> None:
    session.add_all(
        [
            Reading(
                count=n,
                amount=decimal.Decimal(f"{n}.25"),
                day=datetime.date(2026, 1, n),
                at=datetime.time(n, 30),
                taken_at=datetime.datetime.fromisoformat(f"2026-01-01T{10 + n}:00"),
                synced_at=datetime.datetime(2026, 1, 1, 10 + n, tzinfo=datetime.UTC),
                ref=uuid.UUID(int=n),
            )
            for n in (1, 2, 3)
        ]
    )
    await session.commit()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("f.count.min=2", [2, 3]),
        ("f.count.max=3000000000", [1, 2, 3]),
        ("f.count.min=3000000000", []),
        ("f.amount.min=1.3&f.amount.max=2.25", [2]),
        ("f.amount.max=100000000", [1, 2, 3]),
        ("f.day.min=2026-01-02&f.day.max=2026-01-02", [2]),
        ("f.at.max=02:30", [1, 2]),
        ("f.taken_at.min=2026-01-01T13:00%2B02:00", [1, 2, 3]),
        ("f.taken_at.min=2026-01-01T14:00%2B02:00", [2, 3]),
        ("f.ref=000000000003", [3]),
    ],
)
async def test_reading_filters_narrow_rows(
    session: AsyncSession, query: str, expected: list[int]
) -> None:
    await seed_readings(session)
    view = ReadingView()
    stmt = apply_filters(select(Reading.count), Reading, view.filters, parse(view, query))
    assert (await session.scalars(stmt.order_by(Reading.id))).all() == expected


class ScopedUserView(ModelView[User]):
    model = User

    def get_query(self, request: Request) -> Select[User]:
        return super().get_query(request).where(User.email != "hidden@x.io")


async def author_labels(
    factory: AppFactory, session: AsyncSession, query: str, *, registered: bool
) -> list[tuple[str, str]]:
    session.add(User(email="hidden@x.io"))
    session.add_all([User(email=f"u{n:03}@x.io") for n in range(2, 103)])
    await session.commit()
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    if registered:
        admin.register(ScopedUserView)
    request = Request({"type": "http", "method": "GET", "query_string": b"", "headers": []})
    view = PostView()
    labels = await relation_labels(
        admin, request, session, view.filters, parse(view, query), with_options=True
    )
    return labels["author"]


@pytest.mark.anyio
async def test_relation_options_are_scoped_limited_and_keep_the_selection(
    factory: AppFactory, session: AsyncSession
) -> None:
    labels = await author_labels(factory, session, "f.author=102&f.author=1", registered=True)
    assert [pk for pk, _ in labels] == [str(n) for n in range(2, 103)]
    assert labels[-1] == ("102", "u102@x.io")


@pytest.mark.anyio
async def test_relation_options_of_an_unregistered_target_use_the_whole_table(
    factory: AppFactory, session: AsyncSession
) -> None:
    labels = await author_labels(factory, session, "f.author=1", registered=False)
    assert len(labels) == 100
    assert labels[0] == ("1", "hidden@x.io")
