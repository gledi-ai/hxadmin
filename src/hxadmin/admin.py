import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import (
    BaseLoader,
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    PackageLoader,
    select_autoescape,
)
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import BaseRoute

from hxadmin.deps import AuthDependency, SessionDependency
from hxadmin.fields import default_widget
from hxadmin.nav import build_nav, build_search_targets
from hxadmin.pages import AdminPage, PageEndpoint, PageHandler
from hxadmin.toasts import FLASH_COOKIE, Toast, encode_flash, hx_trigger, read_flash
from hxadmin.views import ModelView


def json_pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _first_segment(path: str) -> str:
    return path.strip("/").split("/", 1)[0]


def _require_async_page(path: str, handler: object) -> None:
    if not inspect.iscoroutinefunction(handler):
        raise TypeError(f"Page handler for {path!r} must be an async function")


_PAGE_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")


def _method_not_allowed(allowed: Sequence[str]) -> Callable[[], Awaitable[Response]]:
    """Endpoint answering 405 for a page path, so `/{identity}/{pk}` cannot claim it as a 404."""
    allow = ", ".join(m.upper() for m in allowed)

    async def not_allowed() -> Response:
        return Response(status_code=405, headers={"Allow": allow})

    return not_allowed


class HxAdmin:
    current_user: Callable[..., Awaitable[Any]]
    current_session: Callable[..., Awaitable[AsyncSession]]
    _page_slot: int

    def __init__(
        self,
        app: FastAPI,
        *,
        session: SessionDependency,
        auth: AuthDependency,
        title: str = "HxAdmin",
        prefix: str = "/admin",
        login_url: str | None = None,
        logout_url: str | None = None,
        templates_dir: str | Path | None = None,
    ) -> None:
        self.app = app
        self.title = title
        self.prefix = prefix.rstrip("/")
        self.login_url = login_url
        self.logout_url = logout_url
        self.views: dict[str, ModelView[Any]] = {}
        self.pages: list[AdminPage] = []
        self._page_methods: dict[str, set[str]] = {}
        self._method_fallbacks: dict[str, BaseRoute] = {}
        self._session = session
        self._auth = auth
        self.templates = self._make_environment(templates_dir)
        self.subapp = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        self.subapp.mount(
            "/static",
            StaticFiles(directory=str(Path(__file__).parent / "static")),
            name="static",
        )
        self._build_dependencies()
        self._install_routes()
        self.subapp.add_exception_handler(StarletteHTTPException, self._handle_http_exception)
        app.mount(self.prefix, self.subapp, name="hxadmin")

    def _make_environment(self, templates_dir: str | Path | None) -> Environment:
        loaders: list[BaseLoader] = [PackageLoader("hxadmin", "templates")]
        if templates_dir is not None:
            loaders.insert(0, FileSystemLoader(str(templates_dir)))
        env = Environment(loader=ChoiceLoader(loaders), autoescape=select_autoescape(["html"]))
        env.filters["json_pretty"] = json_pretty
        cast(dict[str, Any], env.globals)["default_widget"] = default_widget
        return env

    def _build_dependencies(self) -> None:
        auth = self._auth
        session = self._session

        async def current_user(request: Request, user: Any = Depends(auth)) -> Any:
            request.state.hxadmin_user = user
            return user

        async def current_session(
            session_: AsyncSession = Depends(session),
        ) -> AsyncSession:
            return session_

        self.current_user = current_user
        self.current_session = current_session

    def _install_routes(self) -> None:
        from hxadmin.routes import build_router

        self._page_slot = len(self.subapp.router.routes)
        self.subapp.include_router(build_router(self))

    async def _handle_http_exception(self, request: Request, exc: Exception) -> Response:
        if not isinstance(exc, StarletteHTTPException):
            raise exc
        htmx = request.headers.get("HX-Request") == "true"
        authenticated = hasattr(request.state, "hxadmin_user")
        if exc.status_code in (401, 403) and self.login_url is not None and not authenticated:
            if htmx:
                return Response(status_code=200, headers={"HX-Redirect": self.login_url})
            return RedirectResponse(self.login_url, status_code=303)
        if htmx:
            toast = Toast(str(exc.detail), "error")
            response: Response = Response(
                status_code=exc.status_code,
                headers={"HX-Trigger": hx_trigger(toast), "HX-Reswap": "none"},
            )
        else:
            response = self.render(
                request,
                "error.html",
                {"status_code": exc.status_code, "detail": exc.detail},
                status_code=exc.status_code,
            )
        response.headers.update(exc.headers or {})
        return response

    def register[V: ModelView[Any]](self, view_cls: type[V]) -> type[V]:
        view = view_cls()
        if view.identity in self.views:
            raise ValueError(f"A view with identity {view.identity!r} is already registered")
        if any(_first_segment(page.path) == view.identity for page in self.pages):
            raise ValueError(f"A page path already uses {view.identity!r}")
        self.views[view.identity] = view
        return view_cls

    def page[F: PageHandler](
        self,
        path: str,
        *,
        title: str,
        category: str | None = None,
        icon: str | None = None,
        methods: Sequence[str] = ("GET",),
        name: str | None = None,
    ) -> Callable[[F], F]:
        """Register a custom page under the admin prefix, guarded by `auth`, in the sidebar."""
        if "{" in path:
            raise ValueError(f"Sidebar page {path!r} cannot take path parameters; use admin.route")
        return self._add_page(AdminPage(path, title, category, icon, in_nav=True), methods, name)

    def route[F: PageHandler](
        self,
        path: str,
        *,
        title: str = "",
        methods: Sequence[str] = ("GET",),
        name: str | None = None,
    ) -> Callable[[F], F]:
        """Register a route under the admin prefix, guarded by `auth`, not in the sidebar."""
        return self._add_page(AdminPage(path, title), methods, name)

    def _add_page[F: PageHandler](
        self, page: AdminPage, methods: Sequence[str], name: str | None
    ) -> Callable[[F], F]:
        self._check_page_path(page.path)
        wanted = {m.upper() for m in methods}
        if "GET" in wanted:
            wanted.add("HEAD")
        clash = wanted & self._page_methods.get(page.path, set())
        if clash:
            raise ValueError(
                f"Page path {page.path!r} is already registered for {', '.join(sorted(clash))}"
            )
        if page.in_nav and any(p.in_nav and p.path == page.path for p in self.pages):
            raise ValueError(f"Page path {page.path!r} is already in the sidebar")

        def decorate(handler: F) -> F:
            _require_async_page(page.path, handler)
            routes = self.subapp.router.routes
            start = len(routes)
            self.subapp.add_api_route(
                page.path,
                PageEndpoint(self, page, handler),
                methods=list(methods),
                name=name or getattr(handler, "__name__", page.path),
                dependencies=[Depends(self.current_user)],
                response_model=None,
                include_in_schema=False,
            )
            added = routes[start:]
            del routes[start:]
            routes[self._page_slot : self._page_slot] = added
            self._page_slot += len(added)
            allowed = self._page_methods.get(page.path, set()) | wanted
            self._page_methods[page.path] = allowed
            self._set_method_fallback(page.path, allowed)
            self.pages.append(page)
            return handler

        return decorate

    def _set_method_fallback(self, path: str, allowed: set[str]) -> None:
        """One 405 route per page path, kept after every page handler and before model routes."""
        routes = self.subapp.router.routes
        old = self._method_fallbacks.pop(path, None)
        if old is not None:
            routes.remove(old)
        other = [m for m in _PAGE_METHODS if m not in allowed]
        if not other:
            return
        self.subapp.add_api_route(
            path,
            _method_not_allowed(sorted(allowed)),
            methods=other,
            dependencies=[Depends(self.current_user)],
            include_in_schema=False,
        )
        route = routes.pop()
        routes.insert(self._page_slot, route)
        self._method_fallbacks[path] = route

    def _check_page_path(self, path: str) -> None:
        first = _first_segment(path)
        if not path.startswith("/") or not first or first.startswith("{"):
            raise ValueError(f"Page path must start with a fixed segment like '/reports': {path!r}")
        if first == "static" or first in self.views:
            raise ValueError(f"Page path {path!r} collides with the admin's {first!r} routes")

    def view_for(self, model: type[Any]) -> ModelView[Any] | None:
        return next((v for v in self.views.values() if v.model is model), None)

    def display(self, obj: Any) -> str:
        view = self.view_for(type(obj))
        return view.display(obj) if view is not None else str(obj)

    def url(self, request: Request, path: str = "/") -> str:
        return f"{request.scope.get('root_path', '')}{path}"

    def redirect(self, request: Request, url: str, *, toast: Toast | None = None) -> Response:
        """Redirect after a successful write: HX-Redirect on 200 for htmx, 303 otherwise.

        A `toast` rides along in a short-lived cookie and is shown on the next full page.
        """
        if request.headers.get("HX-Request") == "true":
            response: Response = Response(status_code=200, headers={"HX-Redirect": url})
        else:
            response = RedirectResponse(url, status_code=303)
        if toast is not None:
            response.set_cookie(
                FLASH_COOKIE,
                encode_flash(toast),
                max_age=60,
                path=self.url(request, "/"),
                httponly=True,
                samesite="lax",
            )
        return response

    def render(
        self,
        request: Request,
        template: str,
        context: Mapping[str, Any] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        consume = request.headers.get("HX-Request") != "true" and FLASH_COOKIE in request.cookies
        flash = read_flash(request) if consume else None
        full_context: dict[str, Any] = {
            "admin": self,
            "request": request,
            "user": getattr(request.state, "hxadmin_user", None),
            "nav": build_nav(self, request),
            "search_targets": build_search_targets(self, request),
            "toasts": [flash.as_dict()] if flash is not None else [],
        }
        if context:
            full_context.update(context)
        html = self.templates.get_template(template).render(full_context)
        response = HTMLResponse(html, status_code=status_code)
        if consume:
            response.delete_cookie(
                FLASH_COOKIE, path=self.url(request, "/"), httponly=True, samesite="lax"
            )
        return response
