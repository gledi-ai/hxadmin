from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin.pk import fetch_by_pks
from hxadmin.query import (
    ListParams,
    apply_search,
    fetch_one,
    parse_list_params,
    run_list,
)
from hxadmin.views import ModelView
from tests.conftest import Group, Post, User, Vote

pytestmark = pytest.mark.anyio


class UserView(ModelView[User]):
    model = User
    searchable = ("email",)
    default_sort = ("email", "asc")
    page_size = 2
    page_size_options = (2, 5)


class PostView(ModelView[Post]):
    model = Post
    list_columns = ("title", "author")
    detail_columns = ("title", "author", "tags")


class VoteView(ModelView[Vote]):
    model = Vote


def _request(query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": query.encode(),
        }
    )


async def _seed_users(session: AsyncSession) -> None:
    g = Group(name="staff")
    session.add_all(
        [
            User(email="carol@x.io", group=g),
            User(email="alice@x.io", active=False),
            User(email="bob@x.io", group=g),
            User(email="dave@y.io"),
            User(email="eve@y.io"),
        ]
    )
    await session.commit()


def test_parse_defaults() -> None:
    params = parse_list_params(_request(), UserView())
    assert params == ListParams(q="", sort="email", dir="asc", page=1, size=2)


def test_parse_valid_values() -> None:
    params = parse_list_params(_request("q=al&sort=id&dir=desc&page=3&size=5"), UserView())
    assert params == ListParams(q="al", sort="id", dir="desc", page=3, size=5)


@pytest.mark.parametrize(
    "query",
    ["sort=group&dir=up&page=0&size=99", "sort=;drop&page=abc&size=x", "page=-4"],
)
def test_parse_invalid_falls_back(query: str) -> None:
    params = parse_list_params(_request(query), UserView())
    assert params == ListParams(q="", sort="email", dir="asc", page=1, size=2)


def test_parse_no_default_sort() -> None:
    params = parse_list_params(_request(), VoteView())
    assert params.sort is None
    assert params.dir == "asc"


def test_qs_round_trip() -> None:
    params = ListParams(q="al", sort="email", dir="asc", page=2, size=5)
    assert params.qs() == "q=al&sort=email&dir=asc&page=2&size=5"
    assert params.qs(page=3) == "q=al&sort=email&dir=asc&page=3&size=5"
    assert ListParams(q="", sort=None, dir="asc", page=1, size=25).qs() == "dir=asc&page=1&size=25"
    assert params.qs(size=None, page=1) == "q=al&sort=email&dir=asc&page=1"


async def test_run_list_sorts_and_paginates(session: AsyncSession) -> None:
    await _seed_users(session)
    view = UserView()
    p1 = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request(), view)
    )
    assert p1.total == 5
    assert p1.pages == 3
    assert (p1.start, p1.end, p1.has_prev, p1.has_next) == (1, 2, False, True)
    assert [u.email for u in p1.rows] == ["alice@x.io", "bob@x.io"]

    p3 = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request("page=3"), view)
    )
    assert [u.email for u in p3.rows] == ["eve@y.io"]
    assert (p3.start, p3.end, p3.has_prev, p3.has_next) == (5, 5, True, False)

    desc = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request("dir=desc"), view)
    )
    assert [u.email for u in desc.rows] == ["eve@y.io", "dave@y.io"]


async def test_run_list_clamps_page_to_last(session: AsyncSession) -> None:
    await _seed_users(session)
    view = UserView()
    result = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request("page=999"), view)
    )
    assert result.params.page == 3
    assert [u.email for u in result.rows] == ["eve@y.io"]
    assert (result.start, result.end) == (5, 5)


async def test_run_list_stable_sort_uses_pk_tiebreaker(session: AsyncSession) -> None:
    await _seed_users(session)
    view = UserView()
    result = await run_list(
        session,
        view,
        view.get_query(_request()),
        parse_list_params(_request("sort=active&dir=asc&size=5"), view),
    )
    assert [u.email for u in result.rows] == [
        "alice@x.io",
        "carol@x.io",
        "bob@x.io",
        "dave@y.io",
        "eve@y.io",
    ]


async def test_run_list_searches_case_insensitively_and_escapes_wildcards(
    session: AsyncSession,
) -> None:
    await _seed_users(session)
    session.add(User(email="100%_sure@z.io"))
    await session.commit()
    view = UserView()
    hit = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request("q=Y.IO"), view)
    )
    assert [u.email for u in hit.rows] == ["dave@y.io", "eve@y.io"]
    pct = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request("q=%25_"), view)
    )
    assert [u.email for u in pct.rows] == ["100%_sure@z.io"]
    empty = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request("q=zzz"), view)
    )
    assert empty.total == 0
    assert empty.pages == 1
    assert (empty.start, empty.end) == (0, 0)


async def test_run_list_eager_loads_single_relations(session: AsyncSession) -> None:
    author = User(email="a@x.io")
    session.add(Post(title="p", author=author))
    await session.commit()
    session.expunge_all()
    view = PostView()
    result = await run_list(
        session, view, view.get_query(_request()), parse_list_params(_request(), view)
    )
    post: Any = result.rows[0]
    assert post.author.email == "a@x.io"


async def test_fetch_one(session: AsyncSession) -> None:
    author = User(email="a@x.io")
    post = Post(title="p", author=author)
    session.add_all([post, Vote(user=author, post=post, value=3)])
    await session.commit()
    session.expunge_all()
    view = PostView()
    found: Any = await fetch_one(
        session, view, view.get_query(_request()), str(post.id), relations=("author",)
    )
    assert found.title == "p"
    assert found.author.email == "a@x.io"
    assert await fetch_one(session, view, view.get_query(_request()), "999") is None
    assert await fetch_one(session, view, view.get_query(_request()), "abc") is None
    vote: Any = await fetch_one(
        session, VoteView(), VoteView().get_query(_request()), f"{author.id};{post.id}"
    )
    assert vote.value == 3


async def test_fetch_one_loads_only_requested_relations(session: AsyncSession) -> None:
    user = User(email="a@x.io", group=Group(name="staff"))
    session.add(user)
    await session.commit()
    pk = str(user.id)
    session.expunge_all()
    view = UserView()
    loaded: Any = await fetch_one(
        session, view, view.get_query(_request()), pk, relations=("group",)
    )
    session.expunge_all()
    assert loaded.group.name == "staff"
    bare: Any = await fetch_one(session, view, view.get_query(_request()), pk)
    session.expunge_all()
    assert "group" not in bare.__dict__


async def test_fetch_by_pks_preserves_order_and_skips_missing(session: AsyncSession) -> None:
    users = [User(email=f"u{i}@x.io") for i in range(3)]
    post = Post(title="p", author=users[0])
    session.add_all([*users, post, Vote(user=users[1], post=post, value=2)])
    await session.commit()
    ids = [u.id for u in users]
    found = await fetch_by_pks(session, User, [str(ids[2]), str(ids[0]), "999", "abc"])
    assert [u.id for u in found] == [ids[2], ids[0]]
    assert await fetch_by_pks(session, User, []) == []
    votes: list[Any] = await fetch_by_pks(session, Vote, [f"{ids[1]};{post.id}"])
    assert [v.value for v in votes] == [2]
    assert await fetch_by_pks(session, Vote, [str(ids[1])]) == []


def test_apply_search_is_noop_without_q_or_searchable() -> None:
    assert "like" not in str(apply_search(select(Post), PostView(), "x")).lower()
    assert "like" not in str(apply_search(select(User), UserView(), "")).lower()
    assert "like" in str(apply_search(select(User), UserView(), "x")).lower()
