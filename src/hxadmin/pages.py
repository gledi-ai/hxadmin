import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin

type PageHandler = Callable[..., Awaitable[Any]]

_REQUEST_PARAM = "hxadmin_request"


@dataclass(frozen=True, slots=True)
class Page:
    """Render `template` inside the admin shell; `context` is merged over the standard one."""

    template: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdminPage:
    """A registered custom page or route; exposed to templates as `page`."""

    path: str
    title: str
    category: str | None = None
    icon: str | None = None
    in_nav: bool = False


class PageEndpoint:
    """FastAPI endpoint around a page handler.

    FastAPI reads `__signature__`: the handler's own parameters (so `Depends`, path and query
    parameters work) plus a `Request` when the handler does not take one. `Page` results are
    rendered in the admin shell; anything else is returned to FastAPI unchanged.
    """

    __signature__: inspect.Signature

    def __init__(self, admin: "HxAdmin", page: AdminPage, handler: PageHandler) -> None:
        self.admin = admin
        self.page = page
        self.handler = handler
        signature = inspect.signature(handler, eval_str=True)
        params = list(signature.parameters.values())
        self.request_param = next((p.name for p in params if p.annotation is Request), None)
        if self.request_param is None:
            params.append(
                inspect.Parameter(
                    _REQUEST_PARAM, inspect.Parameter.KEYWORD_ONLY, annotation=Request
                )
            )
        self.__signature__ = signature.replace(
            parameters=params, return_annotation=inspect.Signature.empty
        )

    async def __call__(self, **kwargs: Any) -> Response:
        if self.request_param is None:
            request = kwargs.pop(_REQUEST_PARAM)
        else:
            request = kwargs[self.request_param]
        result = await self.handler(**kwargs)
        if isinstance(result, Page):
            return self.admin.render(
                request, result.template, {**result.context, "page": self.page}
            )
        return result
