from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import HxAdmin
from hxadmin.fields import Field, RelationField
from hxadmin.views import ModelView
from tests.conftest import AppFactory, Group, Post, PostStatus, User, Vote, allow_all


class UserView(ModelView[User]):
    model = User


class GroupView(ModelView[Group]):
    model = Group
    name = "Team"
    name_plural = "Teams"
    identity = "teams"
    category = "Auth"
    icon = "users"


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_defaults_derive_from_model_name() -> None:
    view = UserView()
    assert view.name == "User"
    assert view.name_plural == "Users"
    assert view.identity == "user"
    assert view.category is None
    assert view.icon is None
    assert view.is_visible(_request()) is True
    assert view.is_accessible(_request()) is True


def test_explicit_attributes_win() -> None:
    view = GroupView()
    assert (view.name, view.name_plural, view.identity) == ("Team", "Teams", "teams")
    assert view.category == "Auth"
    assert view.icon == "users"


def test_subclass_inherits_parent_naming() -> None:
    class Sub(GroupView):
        pass

    assert (Sub.name, Sub.name_plural, Sub.identity) == ("Team", "Teams", "teams")


def test_subclass_redefining_model_rederives_defaults() -> None:
    class Configured(ModelView[Any]):
        model: Any = Group
        name = "Team"
        name_plural = "Teams"
        identity = "teams"

    class Sub(Configured):
        model = User

    assert (Sub.name, Sub.name_plural, Sub.identity) == ("User", "Users", "user")


def test_model_is_required() -> None:
    with pytest.raises(TypeError, match="model"):

        class Broken(ModelView[User]):
            pass


class PostView(ModelView[Post]):
    model = Post
    list_columns = ("title", "status", "author")
    searchable = ("title",)
    default_sort = ("title", "desc")

    def format_title(self, obj: Post) -> str:
        return obj.title.upper()


class VoteView(ModelView[Vote]):
    model = Vote


def test_default_list_and_detail_fields() -> None:
    view = UserView()
    assert [f.name for f in view.list_fields] == ["id", "email", "active", "group_id"]
    assert [f.name for f in view.detail_fields] == [
        "id",
        "email",
        "active",
        "group_id",
        "group",
        "posts",
    ]
    assert view.sort_names == ("id", "email", "active", "group_id")
    assert view.pk_names == ("id",)
    assert view.page_size == 25
    assert view.default_sort is None
    assert view.formatted == frozenset()


def test_explicit_list_columns_resolve_to_fields() -> None:
    view = PostView()
    assert view.list_fields == (
        Field("title", "str", "Title", required=True),
        Field(
            "status",
            "enum",
            "Status",
            required=False,
            default="draft",
            choices=(("draft", "draft"), ("published", "published")),
        ),
        RelationField(
            "author", "Author", User, multiple=False, fk_columns=("author_id",), required=True
        ),
    )
    assert view.sort_names == ("title", "status")
    assert view.formatted == frozenset({"title"})


def test_unknown_column_is_rejected_at_init() -> None:
    class Bad(ModelView[User]):
        model = User
        list_columns = ("nope",)

    with pytest.raises(ValueError, match="nope"):
        Bad()


def test_relation_in_sortable_is_rejected() -> None:
    class Bad(ModelView[User]):
        model = User
        sortable = ("group",)

    with pytest.raises(ValueError, match="group"):
        Bad()


def test_default_sort_must_be_sortable() -> None:
    class Bad(ModelView[User]):
        model = User
        sortable = ("email",)
        default_sort = ("id", "asc")

    with pytest.raises(ValueError, match="id"):
        Bad()


def test_pk_roundtrip_single() -> None:
    view = UserView()
    user = User(id=7, email="a@b.c")
    assert view.pk_of(user) == "7"
    clauses = view.pk_clauses("7")
    assert len(clauses) == 1
    assert "users.id = 7" in str(clauses[0].compile(compile_kwargs={"literal_binds": True}))


def test_pk_roundtrip_composite() -> None:
    view = VoteView()
    assert view.pk_of(Vote(user_id=1, post_id=2)) == "1;2"
    clauses = view.pk_clauses("1;2")
    compiled = [str(c.compile(compile_kwargs={"literal_binds": True})) for c in clauses]
    assert "votes.user_id = 1" in compiled[0]
    assert "votes.post_id = 2" in compiled[1]


def test_integer_pks_bind_as_bigint_so_wide_values_just_miss() -> None:
    stmt = select(User.id).where(*UserView().pk_clauses("3000000000"))
    assert "users.id = $1::BIGINT" in str(stmt.compile(dialect=asyncpg.dialect()))


@pytest.mark.parametrize("pk", ["x", "1;2", ""])
def test_bad_pk_raises(pk: str) -> None:
    with pytest.raises(ValueError, match=r".*"):
        UserView().pk_clauses(pk)


def test_display_uses_str_when_defined() -> None:
    assert UserView().display(User(id=1, email="a@b.c")) == "a@b.c"
    assert VoteView().display(Vote(user_id=1, post_id=2)) == "Vote 1;2"


def test_cell_prefers_formatter() -> None:
    post = Post(title="hello", status=PostStatus.draft)
    view = PostView()
    assert view.cell(post, "title") == "HELLO"
    assert view.cell(post, "status") is PostStatus.draft


def test_get_query_selects_model() -> None:
    stmt = UserView().get_query(_request())
    assert "FROM users" in str(stmt)


def test_admin_view_for_and_display(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    admin.register(UserView)
    assert admin.view_for(User) is admin.views["user"]
    assert admin.view_for(Group) is None
    assert admin.display(User(id=1, email="a@b.c")) == "a@b.c"
    assert admin.display(Vote(user_id=1, post_id=2)).startswith("<tests.conftest.Vote")


def test_default_writable_fields_skip_autoincrement_pk_and_fk_columns() -> None:
    view = PostView()
    assert [f.name for f in view.writable_fields] == [
        "title",
        "body",
        "status",
        "score",
        "published_at",
        "author",
        "tags",
    ]
    assert view.edit_fields == view.writable_fields
    assert view.create_schema is not view.edit_schema
    assert set(view.create_schema.model_fields) == {f.name for f in view.writable_fields}


def test_composite_pk_stays_in_create_form_but_not_edit() -> None:
    view = VoteView()
    assert [f.name for f in view.writable_fields] == ["value", "user", "post"]
    assert [f.name for f in view.edit_fields] == ["value"]


def test_explicit_form_fields_and_exclude() -> None:
    class Configured(ModelView[User]):
        model = User
        form_fields = (
            Field("email", "str", "E-mail", widget="email", help_text="Login name"),
            "active",
            "group",
            "id",
        )
        form_exclude = ("active",)

    view = Configured()
    assert [f.name for f in view.writable_fields] == ["email", "group", "id"]
    email = view.writable_fields[0]
    assert isinstance(email, Field)
    assert (email.label, email.widget, email.help_text) == ("E-mail", "email", "Login name")
    assert (email.unique, email.kind) == (True, "str")
    assert [f.name for f in view.edit_fields] == ["email", "group"]


def test_form_field_override_inherits_required_and_default() -> None:
    class Configured(ModelView[Post]):
        model = Post
        form_fields = (
            Field("title", "str", help_text="t"),
            Field("status", "enum", help_text="s"),
            Field("body", "text", required=True),
            Field("score", "float", default=1.5),
        )

    title, status, body, score = Configured().writable_fields
    assert isinstance(title, Field)
    assert isinstance(status, Field)
    assert isinstance(body, Field)
    assert isinstance(score, Field)
    assert (title.required, title.default) == (True, None)
    assert (status.required, status.default) == (False, "draft")
    assert body.required is True
    assert (score.required, score.default) == (False, 0.0)
    assert all(isinstance(f.required, bool) for f in Configured().writable_fields)


def test_form_field_override_must_be_a_column() -> None:
    class Bad(ModelView[User]):
        model = User
        form_fields = (Field("group", "str"),)

    with pytest.raises(ValueError, match="group"):
        Bad()


def test_unknown_form_field_is_rejected() -> None:
    class Bad(ModelView[User]):
        model = User
        form_fields = ("nope",)

    with pytest.raises(ValueError, match="nope"):
        Bad()


@pytest.mark.anyio
async def test_hooks_default_to_noop(session: AsyncSession) -> None:
    view = UserView()
    user = User(id=1, email="a@b.c")
    assert await view.on_save(_request(), session, user, created=True) is None
    assert await view.on_delete(_request(), session, user) is None
