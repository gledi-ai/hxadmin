"""The user `auth` returned: how the top bar names it, and keeping it loaded after writes."""

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


def user_label(user: Any) -> str:
    """The user's `name` (attribute or mapping key) when set, else `str(user)`.

    `None` and booleans (an `auth` that only answers "allowed") have no label: "".
    """
    if user is None or isinstance(user, bool):
        return ""
    name = user.get("name") if isinstance(user, Mapping) else getattr(user, "name", None)
    label = str(name) if name not in (None, "") else str(user)
    return label.strip()


def user_initials(label: str) -> str:
    """Up to two uppercase initials: from the first two words, or an email's local part."""
    local = label.split("@", 1)[0] if " " not in label else label
    words = re.findall(r"[^\W_]+", local)
    return "".join(w[0] for w in words[:2]).upper()


async def refresh_user(request: Request, session: AsyncSession) -> None:
    """Reload the `auth` user if it is a row of `session` that a commit or rollback expired.

    Hooks and the shell read the user after hxadmin's own writes, and async SQLAlchemy cannot
    lazy-load an expired attribute; any other kind of user is left alone.
    """
    state = inspect(getattr(request.state, "hxadmin_user", None), raiseerr=False)
    if state is None or state.session is not session.sync_session or not state.expired_attributes:
        return
    await session.refresh(state.obj())
