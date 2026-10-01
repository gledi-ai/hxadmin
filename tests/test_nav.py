from starlette.requests import Request

from hxadmin import HxAdmin, ModelView
from hxadmin.nav import NavGroup, NavItem, build_nav
from tests.conftest import AppFactory, Group, User, allow_all


def _request(path: str, root_path: str = "/admin") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": root_path,
            "headers": [],
            "query_string": b"",
        }
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


def test_active_detection_respects_mount_depth(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    nav = build_nav(admin, _request("/api/admin/user/", root_path="/api/admin"))
    assert nav == [NavGroup(label=None, items=(NavItem("Users", "/api/admin/user/", None, True),))]


def test_inaccessible_views_are_left_out_of_the_nav(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.register
    class UserView(ModelView[User]):
        model = User

    @admin.register
    class GroupView(ModelView[Group]):
        model = Group

        def is_accessible(self, request: Request) -> bool:
            return False

    labels = [item.label for group in build_nav(admin, _request("/")) for item in group.items]
    assert labels == ["Users"]
