# Actions

Actions are `async` methods of a view, decorated with `@action`, that run on one row (row actions) or on the checked rows of the list (bulk actions). This page uses the [docs models](getting-started.md#the-models-in-these-docs) and the `auth` from [Auth and sessions](auth.md#auth), which returns the signed-in `User` row.

```python
import hashlib
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin import ActionResult, ModelView, action
from myapp.mail import send_password_reset  # your own mail helper
from myapp.models import PasswordReset, User


@admin.register
class UserView(ModelView[User]):
    model = User

    @action("deactivate", label="Deactivate", bulk=True, confirm="Deactivate selected users?")
    async def deactivate(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        me = request.state.hxadmin_user
        changed = [user for user in objs if user.active and user.id != me.id]
        for user in changed:
            user.active = False
        return ActionResult.message(f"Deactivated {len(changed)} of {len(objs)} selected users.")

    @action("reset_password", label="Reset password")
    async def reset_password(
        self, request: Request, session: AsyncSession, obj: User
    ) -> ActionResult:
        token = secrets.token_urlsafe(32)
        session.add(
            PasswordReset(
                user_id=obj.id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        email = obj.email
        await session.commit()
        await send_password_reset(email, f"https://app.example.com/reset?token={token}")
        return ActionResult.message(f"Reset link sent to {email}.", level="info")
```

`send_password_reset` and the `/reset` page that redeems the token are your application's; hxadmin has no mail or password-reset support of its own.

## How changes are saved

The `session` argument is the request's session, and `obj` / `objs` were loaded through it (by `get_query`). SQLAlchemy tracks changes to loaded objects, so `deactivate` only sets attributes: there is no `session.add` and no commit in it. hxadmin commits after the handler returns, and rolls back if it raises.

Use `session` yourself to:

- add new rows, like the `PasswordReset` above (`session.add`);
- delete rows (`await session.delete(obj)`);
- query other rows, or run a bulk `update()` / `delete()` statement (`await session.execute(...)`);
- commit early, as `reset_password` does.

`reset_password` commits before sending the email because an email cannot be rolled back. If the commit failed after the email went out, the link would point at a token that was never stored. Committing inside the handler is fine: hxadmin's commit afterwards has nothing left to do. Read what you need from `obj` before the commit: a sessionmaker with `expire_on_commit=True` expires every attribute at commit, and reading one afterwards would need a lazy load, which async SQLAlchemy cannot do (`MissingGreenlet`).

`deactivate` only changes data. Whether an inactive user is locked out is up to your application: the `auth` in [Auth and sessions](auth.md#auth) refuses users whose `active` is false, so after this action they can no longer open the admin. It skips the signed-in user so an admin cannot lock themselves out, and its message counts the rows it actually changed.

## Where actions appear

Row actions (the default) receive one object. They appear in each list row's `⋯` menu and on the detail page: as buttons when a view has at most two and none has `confirm`, otherwise in the detail `⋯` menu.

Bulk actions (`bulk=True`) receive the checked rows and appear in the floating bar at the bottom of the viewport once rows are selected (see [Bulk actions](lists.md#bulk-actions)). Only rows on the current page can be checked, so a bulk action gets at most one page of rows. The rows are loaded through `get_query`; checked rows that are no longer in it (deleted meanwhile, or out of the user's scope) are left out. When none is left, the handler is not called and a "No rows selected." warning shows instead.

`confirm` opens the shared confirmation dialog with that text before the action runs.

## Results

Return one of:

- `ActionResult.message(text, level="success" | "info" | "warning" | "error")`: re-render the list or detail panel the action ran from, with a toast;
- `ActionResult.redirect(url)`;
- `ActionResult.response(response)`: any Starlette response, for example a download.

Returning anything else counts as a failure. The toast shows in the bottom-right corner with an icon per level. Toasts pause while hovered, and error toasts stay until dismissed.

A row action that deletes its object should return a redirect, since there is no detail page left to show; if it returns a message, hxadmin falls back to the list:

```python
    @action("purge", label="Delete with tasks", confirm="Delete this user and all their tasks?")
    async def purge(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        await session.execute(delete(Task).where(Task.assignee_id == obj.id))
        await session.delete(obj)
        return ActionResult.redirect(admin.url(request, "/user/"))
```

`admin.url(request, path)` prefixes `path` with the admin's mount point, so the link survives a change of `prefix`. (`delete` is `sqlalchemy.delete` and `Task` comes from the models.)

## Errors

Any exception rolls back and shows a "<label> failed." toast; the traceback goes to the `hxadmin` logger. `HTTPException` is the exception: it propagates, so `raise HTTPException(409, "Already archived.")` shows its detail as an error toast over htmx and as the error page otherwise. To tell the user something without failing, return a message with `level="warning"` or `"error"` instead; the changes made so far are still committed.

## Downloads and GET actions

POST actions (the default) run over htmx. `method="GET"` actions are plain links and form submits, so a returned file downloads:

```python
from starlette.responses import JSONResponse


class UserView(ModelView[User]):
    model = User

    @action("download", label="Download data", method="GET")
    async def download(self, request: Request, session: AsyncSession, obj: User) -> ActionResult:
        await session.refresh(obj, ["tasks"])
        data = {"name": obj.name, "email": obj.email, "tasks": [t.title for t in obj.tasks]}
        headers = {"Content-Disposition": f'attachment; filename="user-{obj.id}.json"'}
        return ActionResult.response(JSONResponse(data, headers=headers))
```

A GET action runs from a plain link, so it must not change data: another site could trigger it (see [Cross-site requests](auth.md#cross-site-requests)). Use POST for anything with side effects.

Handlers get objects without eager-loaded relationships, and async SQLAlchemy cannot lazy-load them: `await session.refresh(obj, ["tasks"])` loads one before you touch it, as above.

## Permissions

Override `is_action_allowed` to limit who may run an action:

```python
class UserView(ModelView[User]):
    model = User

    def is_action_allowed(self, request: Request, name: str) -> bool:
        if name in ("deactivate", "purge"):
            return request.state.hxadmin_user.is_superuser
        return True
```

A disallowed action is not rendered anywhere, and its routes answer 403. `request.state.hxadmin_user` is the value your `auth` dependency returned; with the `auth` from [Getting started](getting-started.md), which returns a plain dict, `.is_superuser` would raise, so check whatever your `auth` returns.
