# Actions

```python
from collections.abc import Sequence

from hxadmin import ActionResult, action


@admin.register
class UserView(ModelView[User]):
    model = User

    @action("deactivate", label="Deactivate", bulk=True, confirm="Deactivate selected users?")
    async def deactivate(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        for user in objs:
            user.active = False
        return ActionResult.message(f"Deactivated {len(objs)} users")

    @action("reset_password", label="Reset password")
    async def reset_password(
        self, request: Request, session: AsyncSession, obj: User
    ) -> ActionResult:
        ...
        return ActionResult.message("Reset link sent", level="info")
```

Row actions (the default) receive one object. They appear in each list row's `⋯` menu and on the detail page: as buttons when a view has at most two and none has `confirm`, otherwise in the detail `⋯` menu. Bulk actions receive the checked rows, always loaded through `get_query`, and appear in the floating bar at the bottom of the viewport once rows are selected (see [Bulk actions](lists.md#bulk-actions)). `confirm` opens the shared confirmation dialog.

The result shows as a toast in the bottom-right corner with an icon per level. Toasts pause while hovered, and error toasts stay until dismissed.

Return one of:

- `ActionResult.message(text, level="success" | "info" | "warning" | "error")`: re-render the view with a toast;
- `ActionResult.redirect(url)`;
- `ActionResult.response(response)`: any Starlette response, for example a download.

hxadmin commits after the handler returns. Any exception rolls back and shows a "<label> failed." toast (the traceback goes to the `hxadmin` logger), except `HTTPException`, which propagates.

POST actions run over htmx. `method="GET"` actions are plain links and form submits, so a returned file downloads. A GET action runs from a plain link, so it must not change data: another site could trigger it. Use POST for anything with side effects.

Handlers get objects without eager-loaded relationships: `await session.refresh(obj, ["group"])` before touching one. A row action that deletes its object should return a redirect; if it returns a message, hxadmin falls back to the list.

## Permissions

Override `is_action_allowed` to limit who may run an action:

```python
class UserView(ModelView[User]):
    def is_action_allowed(self, request: Request, name: str) -> bool:
        return name != "deactivate" or request.state.hxadmin_user.is_superuser
```

A disallowed action is not rendered anywhere, and its routes answer 403. `request.state.hxadmin_user` is the value your `auth` dependency returned.
