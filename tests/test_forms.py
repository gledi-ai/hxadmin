from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData
from starlette.requests import Request

from hxadmin import HxAdmin
from hxadmin.fields import Field
from hxadmin.forms import apply, build_schema, initial_values, parse_form, relabel, validate
from hxadmin.views import ModelView
from tests.conftest import AppFactory, Post, PostStatus, Tag, User, allow_all


class PostView(ModelView[Post]):
    model = Post


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def _admin(factory: AppFactory) -> HxAdmin:
    return HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)


def test_schema_types_and_requiredness() -> None:
    schema = build_schema(Post, PostView().writable_fields)
    names = set(schema.model_fields)
    assert names == {"title", "body", "status", "score", "published_at", "author", "tags"}
    assert schema.model_fields["title"].is_required()
    assert schema.model_fields["author"].is_required()
    assert not schema.model_fields["published_at"].is_required()
    assert not schema.model_fields["tags"].is_required()

    ok = schema.model_validate(
        {"title": "Hi", "status": "draft", "score": "1.5", "author": "1", "tags": ["1", "2"]}
    )
    data: dict[str, Any] = ok.model_dump()
    assert data["score"] == 1.5
    assert data["tags"] == ["1", "2"]
    assert data["published_at"] is None
    assert data["body"] is None


def test_schema_errors() -> None:
    schema = build_schema(Post, PostView().writable_fields)
    with pytest.raises(ValidationError) as info:
        schema.model_validate({"title": "", "status": "nope", "score": "x", "author": None})
    locs = {e["loc"][0] for e in info.value.errors()}
    assert locs == {"title", "status", "score", "author"}


def test_schema_json_bool_datetime_decimal() -> None:
    fields = (
        Field("payload", "json"),
        Field("flag", "bool"),
        Field("when", "datetime", required=True),
        Field("amount", "decimal", required=True),
    )
    schema = build_schema(Post, fields)
    ok = schema.model_validate(
        {"payload": '{"a": 1}', "flag": "on", "when": "2026-09-22T10:30", "amount": "3.10"}
    )
    data: dict[str, Any] = ok.model_dump()
    assert data == {
        "payload": {"a": 1},
        "flag": True,
        "when": datetime.fromisoformat("2026-09-22T10:30"),
        "amount": Decimal("3.10"),
    }
    with pytest.raises(ValidationError):
        schema.model_validate({"payload": "{not json", "when": "x", "amount": "y"})


def test_readonly_fields_are_not_in_schema() -> None:
    schema = build_schema(Post, (Field("title", "str", readonly=True), Field("body", "text")))
    assert set(schema.model_fields) == {"body"}


def test_parse_form_normalises_empty_checkbox_and_multi() -> None:
    view = PostView()
    form = FormData(
        [
            ("title", " Hi "),
            ("body", ""),
            ("status", "draft"),
            ("score", ""),
            ("published_at", ""),
            ("author", "1"),
            ("tags", "1"),
            ("tags", "2"),
            ("tags", ""),
        ]
    )
    raw = parse_form(view.writable_fields, form, created=True)
    assert raw == {
        "title": " Hi ",
        "body": "",
        "status": "draft",
        "published_at": None,
        "author": "1",
        "tags": ["1", "2"],
    }


def test_parse_form_empty_defaulted_column_is_omitted_on_create_and_kept_on_edit() -> None:
    fields = PostView().writable_fields
    form = FormData([("score", ""), ("status", "")])
    assert "score" not in parse_form(fields, form, created=True)
    assert "status" not in parse_form(fields, form, created=True)
    edited = parse_form(fields, form, created=False)
    assert edited["score"] == ""
    assert edited["status"] == ""


def test_validate_reports_empty_non_nullable_column_as_required() -> None:
    view = PostView()
    _, errors = validate(view.edit_schema, {"title": "x", "score": "", "status": "", "author": "1"})
    assert errors.fields["score"] == "This field is required."
    assert errors.fields["status"] == "This field is required."


def test_validate_leaves_omitted_fields_out_of_values() -> None:
    view = PostView()
    values, errors = validate(view.create_schema, {"title": "x", "status": "draft", "author": "1"})
    assert not errors
    assert "score" not in values
    assert "body" not in values


def test_build_schema_derives_required_from_nullable_when_unset() -> None:
    schema = build_schema(Post, (Field("score", "float"), Field("note", "str", nullable=True)))
    assert validate(schema, {"score": ""})[1].fields["score"] == "This field is required."
    values, errors = validate(schema, {"score": "1.5", "note": None})
    assert not errors
    assert values == {"score": 1.5, "note": None}


def test_parse_form_keeps_empty_required_string_and_missing_bool() -> None:
    class UserView(ModelView[User]):
        model = User

    raw = parse_form(UserView().writable_fields, FormData([("email", "")]), created=True)
    assert raw["email"] == ""
    assert raw["active"] is False
    assert raw["group"] is None


def test_parse_form_skips_readonly_fields() -> None:
    fields = (Field("title", "str", readonly=True), Field("body", "text"))
    raw = parse_form(fields, FormData([("title", "x"), ("body", "y")]), created=True)
    assert raw == {"body": "y"}


def test_validate_maps_errors_per_field() -> None:
    view = PostView()
    values, errors = validate(view.create_schema, {"title": "", "status": "x", "author": None})
    assert values == {}
    assert errors
    assert errors.fields["title"] == "This field is required."
    assert errors.fields["author"] == "This field is required."
    assert "status" in errors.fields
    assert errors.form is None


def test_validate_success_strips_strings() -> None:
    values, errors = validate(
        PostView().create_schema, {"title": " Hi ", "status": "draft", "author": "1", "tags": []}
    )
    assert not errors
    assert values["title"] == "Hi"


@pytest.mark.anyio
async def test_apply_sets_columns_enum_and_relations(
    factory: AppFactory, session: AsyncSession
) -> None:
    ada = User(email="ada@x.io")
    t1, t2 = Tag(name="a"), Tag(name="b")
    session.add_all([ada, t1, t2])
    await session.commit()
    view = PostView()
    post = Post()
    await apply(
        _admin(factory),
        _request(),
        session,
        view,
        post,
        {
            "title": "Hi",
            "body": None,
            "status": "published",
            "score": 2.0,
            "published_at": None,
            "author": "1",
            "tags": ["2", "1"],
        },
        view.writable_fields,
    )
    assert post.title == "Hi"
    assert post.status is PostStatus.published
    assert post.author is ada
    assert [t.name for t in post.tags] == ["b", "a"]


@pytest.mark.anyio
async def test_apply_unknown_relation_pk_raises_lookup_error(
    factory: AppFactory, session: AsyncSession
) -> None:
    admin = _admin(factory)
    view = PostView()
    fields = view.writable_fields
    with pytest.raises(LookupError, match="author"):
        await apply(admin, _request(), session, view, Post(), {"author": "999"}, fields)
    with pytest.raises(LookupError, match="tags"):
        await apply(admin, _request(), session, view, Post(), {"tags": ["1", "999"]}, fields)


@pytest.mark.anyio
async def test_apply_and_relabel_use_target_view_scope(
    factory: AppFactory, session: AsyncSession
) -> None:
    session.add_all([User(email="ada@x.io"), User(email="bob@x.io", active=False)])
    await session.commit()
    admin = _admin(factory)
    admin.register(PostView)

    @admin.register
    class ActiveUsers(ModelView[User]):
        model = User

        def get_query(self, request: Request) -> Select[tuple[User]]:
            return select(User).where(User.active.is_(True))

    view = admin.views["post"]
    post = Post()
    await apply(admin, _request(), session, view, post, {"author": "1"}, view.writable_fields)
    assert post.author.email == "ada@x.io"
    with pytest.raises(LookupError, match="author"):
        await apply(admin, _request(), session, view, Post(), {"author": "2"}, view.writable_fields)
    shown = await relabel(admin, _request(), session, view.writable_fields, {"author": "2"})
    assert shown["author"] == []


@pytest.mark.anyio
async def test_apply_and_relabel_treat_inaccessible_target_as_unknown(
    factory: AppFactory, session: AsyncSession
) -> None:
    session.add(User(email="ada@x.io"))
    await session.commit()
    admin = _admin(factory)
    admin.register(PostView)

    @admin.register
    class Locked(ModelView[User]):
        model = User

        def is_accessible(self, request: Request) -> bool:
            return False

    view = admin.views["post"]
    with pytest.raises(LookupError, match="author"):
        await apply(admin, _request(), session, view, Post(), {"author": "1"}, view.writable_fields)
    shown = await relabel(admin, _request(), session, view.writable_fields, {"author": "1"})
    assert shown["author"] == []


def test_initial_values_create_uses_defaults(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    admin.register(PostView)
    view = admin.views["post"]
    values = initial_values(admin, view, None, view.writable_fields)
    assert values["status"] == "draft"
    assert values["body"] == ""
    assert values["title"] is None
    assert values["author"] == []
    assert values["tags"] == []


def test_initial_values_create_bool_defaults_to_false(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    view = PostView()
    values = initial_values(admin, view, None, (Field("flag", "bool"),))
    assert values["flag"] is False


def test_initial_values_edit_reads_object_and_relations(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    admin.register(PostView)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    @admin.register
    class TagView(ModelView[Tag]):
        model = Tag

    view = admin.views["post"]
    ada = User(id=3, email="ada@x.io")
    post = Post(title="Hi", status=PostStatus.published, author=ada, tags=[Tag(id=5, name="t")])
    values = initial_values(admin, view, post, view.edit_fields)
    assert values["status"] == "published"
    assert values["author"] == [("3", "ada@x.io")]
    assert values["tags"] == [("5", "Tag 5")]
