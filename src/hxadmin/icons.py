"""Inline Lucide icons from the SVGs vendored in `static/vendor/lucide`."""

import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from markupsafe import escape

_ICONS = files("hxadmin").joinpath("static", "vendor", "lucide")
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_BODY = re.compile(r"<svg\b[^>]*>(.*)</svg>", re.DOTALL)
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


def is_icon(name: str) -> bool:
    """Whether `name` is a vendored Lucide icon."""
    return _NAME.fullmatch(name) is not None and _ICONS.joinpath(f"{name}.svg").is_file()


def check_icon(name: str | None) -> None:
    """Raise `ValueError` unless `name` is None or a vendored Lucide icon."""
    if name is not None and not is_icon(name):
        raise ValueError(
            f"Unknown icon {name!r}: use a Lucide icon name (https://lucide.dev/icons)"
        )


@cache
def _shapes(name: str) -> str:
    check_icon(name)
    source = _ICONS.joinpath(f"{name}.svg").read_text(encoding="utf-8")
    match = _BODY.search(source)
    if match is None:
        raise ValueError(f"Icon {name!r} is not a valid SVG")
    return re.sub(r">\s+<", "><", match.group(1).strip())


def icon(name: str, class_: str = "size-4") -> Icon:
    """The Lucide icon `name` as inline SVG, sized by `class_` and hidden from assistive tech."""
    _shapes(name)
    return Icon(name, class_)
