import pytest
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
)
from sqlalchemy.types import TypeEngine

from hxadmin.fields import Field, RelationField, derive_fields, kind_for, label_for
from tests.conftest import Post, PostStatus, Tag, User, Vote


@pytest.mark.parametrize(
    ("type_", "kind"),
    [
        (String(), "str"),
        (Text(), "text"),
        (Integer(), "int"),
        (BigInteger(), "int"),
        (Float(), "float"),
        (Numeric(10, 2), "decimal"),
        (Boolean(), "bool"),
        (Date(), "date"),
        (DateTime(), "datetime"),
        (Time(), "time"),
        (Enum(PostStatus), "enum"),
        (JSON(), "json"),
        (Uuid(), "uuid"),
        (LargeBinary(), "str"),
    ],
)
def test_kind_for(type_: TypeEngine[object], kind: str) -> None:
    assert kind_for(type_) == kind


def test_label_for() -> None:
    assert label_for("created_at") == "Created at"
    assert label_for("id") == "Id"


def test_derive_columns_and_relations() -> None:
    fields = derive_fields(Post)
    assert list(fields) == [
        "id",
        "title",
        "body",
        "status",
        "score",
        "published_at",
        "author_id",
        "author",
        "tags",
    ]
    assert fields["id"] == Field("id", "int", "Id", nullable=False, primary_key=True)
    assert fields["body"] == Field("body", "text", "Body")
    assert fields["status"] == Field("status", "enum", "Status")
    assert fields["published_at"] == Field(
        "published_at", "datetime", "Published at", nullable=True
    )
    assert fields["author"] == RelationField("author", "Author", User, multiple=False)
    assert fields["tags"] == RelationField("tags", "Tags", Tag, multiple=True)
    assert fields["tags"].kind == "relation"


def test_derive_composite_primary_key() -> None:
    fields = derive_fields(Vote)
    assert [f.name for f in fields.values() if isinstance(f, Field) and f.primary_key] == [
        "user_id",
        "post_id",
    ]
