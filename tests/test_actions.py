from collections.abc import Sequence
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import PlainTextResponse

import hxadmin
from hxadmin import ActionResult, ModelView, action
from hxadmin.actions import ACTION_ATTR, Action
from hxadmin.toasts import Toast
from tests.conftest import User


class UserView(ModelView[User]):
    model = User

    @action("deactivate", bulk=True, confirm="Sure?")
    async def deactivate(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        return ActionResult.message(f"{len(objs)}")

    @action("send-invite", method="GET")
    async def invite(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.redirect("/x")

    @action("reset_password", label="Reset password…")
    async def reset(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.message("ok")


def test_decorator_records_metadata_and_returns_function() -> None:
    assert getattr(UserView.deactivate, ACTION_ATTR) == Action(
        "deactivate", "Deactivate", True, "Sure?", "POST"
    )
    assert getattr(UserView.invite, ACTION_ATTR) == Action(
        "send-invite", "Send invite", False, None, "GET"
    )


def test_view_collects_row_and_bulk_actions_in_definition_order() -> None:
    view = UserView()
    assert list(view.actions) == ["deactivate", "send-invite", "reset_password"]
    assert [a.name for a in view.row_actions] == ["send-invite", "reset_password"]
    assert [a.name for a in view.bulk_actions] == ["deactivate"]
    assert view.actions["reset_password"].label == "Reset password…"


@pytest.mark.anyio
async def test_action_handler_is_the_bound_method() -> None:
    view = UserView()
    handler = view.action_handler("reset_password")
    result = await handler(cast(Request, None), cast(AsyncSession, None), User(email="a"))
    assert result == ActionResult.message("ok")


def test_subclass_inherits_overrides_and_removes_actions() -> None:
    class Child(UserView):
        @action("deactivate", bulk=True, label="Disable")
        async def deactivate(
            self, request: Request, session: AsyncSession, objs: Sequence[User]
        ) -> ActionResult:
            return ActionResult.message("child")

        async def invite(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
            return ActionResult.message("plain")

    view = Child()
    assert list(view.actions) == ["deactivate", "reset_password"]
    assert view.actions["deactivate"].label == "Disable"


def test_views_without_actions_have_empty_collections() -> None:
    class Plain(ModelView[User]):
        model = User

    view = Plain()
    assert view.actions == {}
    assert view.row_actions == ()
    assert view.bulk_actions == ()


def test_duplicate_action_names_are_rejected() -> None:
    class Bad(ModelView[User]):
        model = User

        @action("go")
        async def one(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
            return ActionResult.message("1")

        @action("go")
        async def two(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
            return ActionResult.message("2")

    with pytest.raises(ValueError, match="duplicate action 'go'"):
        Bad()


@pytest.mark.parametrize("name", ["", "has space", "slash/y", "dot.name", "semi;colon"])
def test_invalid_action_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid action name"):
        action(name)


def test_invalid_method_is_rejected() -> None:
    with pytest.raises(ValueError, match="method must be"):
        action("x", method=cast(Any, "PUT"))


def test_sync_handler_is_rejected() -> None:
    def handler(self: object, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        return ActionResult.message("x")

    with pytest.raises(TypeError, match="must be an async function"):
        action("x")(cast(Any, handler))


def test_action_result_constructors() -> None:
    response = PlainTextResponse("hi")
    assert ActionResult.message("Done") == ActionResult(toast=Toast("Done", "success"))
    assert ActionResult.message("Careful", level="warning").toast == Toast("Careful", "warning")
    assert ActionResult.redirect("/x") == ActionResult(url="/x")
    assert ActionResult.response(response).raw is response


def test_public_exports() -> None:
    assert hxadmin.action is action
    assert hxadmin.ActionResult is ActionResult
    assert {"action", "ActionResult"} <= set(hxadmin.__all__)
