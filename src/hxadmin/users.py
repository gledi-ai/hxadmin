"""How the top bar names the user `auth` returned, whatever its type."""

import re
from collections.abc import Mapping
from typing import Any


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
