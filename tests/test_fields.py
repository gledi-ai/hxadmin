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

from hxadmin.fields import (
    Field,
    RelationField,
    default_widget,
    derive_fields,
    kind_for,
    label_for,
)
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
        (LargeBinary(), "other"),
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
    assert fields["id"] == Field(
        "id", "int", "Id", primary_key=True, autoincrement=True, required=False
    )
    assert fields["title"] == Field("title", "str", "Title", required=True)
    assert fields["body"] == Field("body", "text", "Body", required=False, default="")
    assert fields["status"] == Field(
        "status",
        "enum",
        "Status",
        required=False,
        default="draft",
        choices=(("draft", "draft"), ("published", "published")),
    )
    assert fields["published_at"] == Field(
        "published_at", "datetime", "Published at", nullable=True, required=False
    )
    assert fields["author"] == RelationField(
        "author", "Author", User, multiple=False, fk_columns=("author_id",), required=True
    )
    assert fields["tags"] == RelationField("tags", "Tags", Tag, multiple=True)
    assert fields["tags"].kind == "relation"


def test_derive_composite_primary_key() -> None:
    fields = derive_fields(Vote)
    assert [f.name for f in fields.values() if isinstance(f, Field) and f.primary_key] == [
        "user_id",
        "post_id",
    ]


def test_field_label_defaults_from_name() -> None:
    assert Field("created_at", "datetime").label == "Created at"
    assert Field("created_at", "datetime", "When").label == "When"


def test_default_widget() -> None:
    assert default_widget("str") == "text"
    assert default_widget("text") == "textarea"
    assert default_widget("bool") == "checkbox"
    assert default_widget("datetime") == "datetime-local"
    assert default_widget("enum") == "select"
    assert default_widget("decimal") == "number"
    assert default_widget("json") == "json"


def test_derive_form_metadata() -> None:
    fields = derive_fields(Post)
    id_ = fields["id"]
    assert isinstance(id_, Field)
    assert (id_.primary_key, id_.autoincrement, id_.required) == (True, True, False)
    title = fields["title"]
    assert isinstance(title, Field)
    assert (title.required, title.default, title.unique) == (True, None, False)
    body = fields["body"]
    assert isinstance(body, Field)
    assert (body.required, body.default) == (False, "")
    status = fields["status"]
    assert isinstance(status, Field)
    assert status.choices == (("draft", "draft"), ("published", "published"))
    assert status.default == "draft"
    assert status.required is False
    published = fields["published_at"]
    assert isinstance(published, Field)
    assert (published.nullable, published.required) == (True, False)
    author = fields["author"]
    assert isinstance(author, RelationField)
    assert author.fk_columns == ("author_id",)
    assert author.required is True
    tags = fields["tags"]
    assert isinstance(tags, RelationField)
    assert tags.fk_columns == ()
    assert tags.required is False


def test_derive_bool_and_nullable_relation() -> None:
    fields = derive_fields(User)
    email = fields["email"]
    assert isinstance(email, Field)
    assert email.unique is True
    active = fields["active"]
    assert isinstance(active, Field)
    assert (active.required, active.default) == (False, True)
    group = fields["group"]
    assert isinstance(group, RelationField)
    assert (group.fk_columns, group.required) == (("group_id",), False)
    posts = fields["posts"]
    assert isinstance(posts, RelationField)
    assert posts.fk_columns == ()


def test_composite_pk_is_not_autoincrement() -> None:
    fields = derive_fields(Vote)
    for name in ("user_id", "post_id"):
        f = fields[name]
        assert isinstance(f, Field)
        assert (f.primary_key, f.autoincrement, f.required) == (True, False, True)


def test_field_widget_and_width() -> None:
    from hxadmin.fields import field_widget, field_width

    assert field_widget(Field("n", "int")) == "number"
    assert field_widget(Field("n", "str", widget="email")) == "email"
    single = RelationField("author", "Author", User, multiple=False)
    many = RelationField("tags", "Tags", Tag, multiple=True)
    assert field_widget(single) == "relation"
    short = (Field("n", "int"), Field("n", "bool"), Field("n", "date"), Field("n", "enum"), single)
    assert [field_width(f) for f in short] == ["half"] * 5
    long = (Field("n", "str"), Field("n", "text"), Field("n", "json"), many)
    assert [field_width(f) for f in long] == ["full"] * 4
