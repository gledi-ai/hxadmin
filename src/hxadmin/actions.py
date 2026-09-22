import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Self

from starlette.responses import Response

from hxadmin.fields import label_for
from hxadmin.toasts import Toast, ToastLevel

type ActionMethod = Literal["GET", "POST"]
type ActionHandler = Callable[..., Awaitable[Any]]

ACTION_ATTR = "__hxadmin_action__"
_NAME = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class Action:
    """Metadata declared by one `@action` method."""

    name: str
    label: str
    bulk: bool
    confirm: str | None
    method: ActionMethod


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Outcome of an action: a toast over the re-rendered view, a redirect, or a raw response."""

    toast: Toast | None = None
    url: str | None = None
    raw: Response | None = None

    @classmethod
    def message(cls, text: str, level: ToastLevel = "success") -> Self:
        return cls(toast=Toast(text, level))

    @classmethod
    def redirect(cls, url: str) -> Self:
        return cls(url=url)

    @classmethod
    def response(cls, response: Response) -> Self:
        return cls(raw=response)


def _require_async(name: str, func: object) -> None:
    if not inspect.iscoroutinefunction(func):
        raise TypeError(f"Action {name!r} must be an async function")


def action[F: ActionHandler](
    name: str,
    *,
    label: str | None = None,
    bulk: bool = False,
    confirm: str | None = None,
    method: ActionMethod = "POST",
) -> Callable[[F], F]:
    """Declare a `ModelView` coroutine method as a row action, or a bulk action with `bulk=True`.

    Row handlers receive `(request, session, obj)`, bulk handlers `(request, session, objs)`.
    POST actions run over htmx; `method="GET"` actions are plain links / form submits so a
    returned download reaches the browser.
    """
    if not _NAME.fullmatch(name):
        raise ValueError(f"Invalid action name {name!r}: use letters, digits, '_' and '-'")
    if method not in ("GET", "POST"):
        raise ValueError(f"Action {name!r}: method must be 'GET' or 'POST', not {method!r}")
    spec = Action(name, label or label_for(name.replace("-", "_")), bulk, confirm, method)

    def decorate(func: F) -> F:
        _require_async(name, func)
        setattr(func, ACTION_ATTR, spec)
        return func

    return decorate
