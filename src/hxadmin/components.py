"""Helpers the component macros in `templates/components/` call as Jinja globals."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jinja2 import Undefined
from markupsafe import escape

_NAME = re.compile(r"[@:A-Za-z_][\w.:@-]*")


@dataclass(frozen=True, slots=True)
class Attributes:
    """Extra HTML attributes that render themselves (Jinja treats them as safe markup).

    Each pair is a name and an escaped value, or None for a bare boolean attribute.
    """

    pairs: tuple[tuple[str, str | None], ...]

    def __html__(self) -> str:
        return "".join(f" {k}" if v is None else f' {k}="{v}"' for k, v in self.pairs)

    def __str__(self) -> str:
        return self.__html__()


def html_attrs(
    attrs: Mapping[str, Any] | None = None, kwargs: Mapping[str, Any] | None = None
) -> Attributes:
    """Render `attrs` as-is and `kwargs` with `_` turned into `-`, later keys winning.

    None, False and undefined values are dropped, True renders a bare attribute and anything
    else is escaped. Names must look like HTML, Alpine or htmx attribute names, and `class`
    is rejected because every component takes it as its own argument.
    """
    merged: dict[str, Any] = {}
    for key, value in (attrs or {}).items():
        merged[key] = value
    for key, value in (kwargs or {}).items():
        merged[key.replace("_", "-")] = value
    pairs: list[tuple[str, str | None]] = []
    for key, value in merged.items():
        if not _NAME.fullmatch(key):
            raise ValueError(f"Invalid attribute name {key!r}")
        if key == "class":
            raise ValueError("Pass class as the component's class argument, not as an attribute")
        if value is None or value is False or isinstance(value, Undefined):
            continue
        pairs.append((key, None if value is True else str(escape(value))))
    return Attributes(tuple(pairs))


def pick(options: Mapping[str, str], key: str, what: str) -> str:
    """`options[key]`, or a `ValueError` naming `what` and the allowed keys."""
    try:
        return options[key]
    except KeyError:
        allowed = ", ".join(options)
        raise ValueError(f"Unknown {what} {key!r}: use one of {allowed}") from None
