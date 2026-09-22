from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from hxadmin.nav import NavGroup, NavItem, build_nav
from tests.conftest import AppFactory, Group, User, allow_all


def _request(path: str) -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""}
    )


def test_groups_by_category_in_registration_order(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group
        category = "Auth"
        icon = "users"

    @admin.register
    class UserView(ModelView[User]):
        model = User

    nav = build_nav(admin, _request("/admin/group/"))
    assert nav == [
        NavGroup(label=None, items=(NavItem("Users", "/admin/user/", None, False),)),
        NavGroup(label="Auth", items=(NavItem("Groups", "/admin/group/", "users", True),)),
    ]


def test_hidden_views_are_omitted(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

        def is_visible(self, request: Request) -> bool:
            return False

    assert build_nav(admin, _request("/admin/")) == []
