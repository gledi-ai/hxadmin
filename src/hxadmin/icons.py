"""Inline Lucide icons from the bundle vendored at `static/vendor/lucide.json`."""

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from markupsafe import escape

_BUNDLE = files("hxadmin").joinpath("static", "vendor", "lucide.json")
_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
)


@dataclass(frozen=True, slots=True)
class Icon:
    """A Lucide icon that renders itself as inline SVG (Jinja treats it as safe markup)."""

    name: str
    class_: str = "size-4"

    def __html__(self) -> str:
        return (
            f'{_OPEN} class="{escape(self.class_)}" aria-hidden="true">{_shapes(self.name)}</svg>'
        )

    def __str__(self) -> str:
        return self.__html__()


@cache
def _icons() -> dict[str, str]:
    return json.loads(_BUNDLE.read_text(encoding="utf-8"))


def is_icon(name: str) -> bool:
    """Whether `name` is a vendored Lucide icon."""
    return name in _icons()


def check_icon(name: str | None) -> None:
    """Raise `ValueError` unless `name` is None or a vendored Lucide icon."""
    if name is not None and not is_icon(name):
        raise ValueError(
            f"Unknown icon {name!r}: use a Lucide icon name (https://lucide.dev/icons)"
        )


def _shapes(name: str) -> str:
    check_icon(name)
    return _icons()[name]


def icon(name: str, class_: str = "size-4") -> Icon:
    """The Lucide icon `name` as inline SVG, sized by `class_` and hidden from assistive tech."""
    _shapes(name)
    return Icon(name, class_)
