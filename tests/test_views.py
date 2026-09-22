from starlette.requests import Request

from hxadmin.views import ModelView
from tests.conftest import Group, User


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


def test_model_is_required() -> None:
    import pytest

    with pytest.raises(TypeError, match="model"):

        class Broken(ModelView[User]):
            pass
