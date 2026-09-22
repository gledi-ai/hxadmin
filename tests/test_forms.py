from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from hxadmin.fields import Field
from hxadmin.forms import build_schema
from hxadmin.views import ModelView
from tests.conftest import Post


class PostView(ModelView[Post]):
    model = Post


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
