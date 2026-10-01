import json
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import quote, unquote

from starlette.requests import Request

type ToastLevel = Literal["success", "info", "warning", "error"]

TOAST_EVENT = "hxadmin-toast"
FLASH_COOKIE = "hxadmin_toast"
_FLASH_MAX_CHARS = 200
_LEVELS: frozenset[str] = frozenset(("success", "info", "warning", "error"))


@dataclass(frozen=True, slots=True)
class Toast:
    """A short notification shown bottom-right in the admin shell."""

    message: str
    level: ToastLevel = "success"

    def as_dict(self) -> dict[str, str]:
        return {"message": self.message, "level": self.level}


def hx_trigger(toast: Toast) -> str:
    """`HX-Trigger` header value that makes the layout show `toast` (ASCII-only JSON)."""
    return json.dumps({TOAST_EVENT: {"target": "body", **toast.as_dict()}})


def encode_flash(toast: Toast) -> str:
    """Flash-cookie value for `toast`; long messages are cut so the cookie stays under 4 KB."""
    message = toast.message
    if len(message) > _FLASH_MAX_CHARS:
        message = message[:_FLASH_MAX_CHARS] + "…"
    return quote(json.dumps({"message": message, "level": toast.level}), safe="")


def read_flash(request: Request) -> Toast | None:
    """The toast carried by the flash cookie, or None if absent or malformed."""
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    try:
        data: Any = json.loads(unquote(raw))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    message, level = data.get("message"), data.get("level")
    if not isinstance(message, str) or level not in _LEVELS:
        return None
    return Toast(message, cast(ToastLevel, level))
