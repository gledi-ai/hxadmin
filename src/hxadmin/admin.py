import json
from collections.abc import Awaitable, Callable, Mapping
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

from hxadmin.deps import AuthDependency, SessionDependency
from hxadmin.fields import default_widget
from hxadmin.nav import build_nav
from hxadmin.views import ModelView


def json_pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


class HxAdmin:
    current_user: Callable[..., Awaitable[Any]]
    current_session: Callable[..., Awaitable[AsyncSession]]

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

        self.subapp.include_router(build_router(self))

    async def _handle_http_exception(self, request: Request, exc: Exception) -> Response:
        if not isinstance(exc, StarletteHTTPException):
            raise exc
        if exc.status_code in (401, 403) and self.login_url is not None:
            if request.headers.get("HX-Request") == "true":
                return Response(status_code=200, headers={"HX-Redirect": self.login_url})
            return RedirectResponse(self.login_url, status_code=303)
        return self.render(
            request,
            "error.html",
            {"status_code": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    def register[V: ModelView[Any]](self, view_cls: type[V]) -> type[V]:
        view = view_cls()
        if view.identity in self.views:
            raise ValueError(f"A view with identity {view.identity!r} is already registered")
        self.views[view.identity] = view
        return view_cls

    def view_for(self, model: type[Any]) -> ModelView[Any] | None:
        return next((v for v in self.views.values() if v.model is model), None)

    def display(self, obj: Any) -> str:
        view = self.view_for(type(obj))
        return view.display(obj) if view is not None else str(obj)

    def url(self, request: Request, path: str = "/") -> str:
        return f"{request.scope.get('root_path', '')}{path}"

    def redirect(self, request: Request, url: str) -> Response:
        """Redirect after a successful write: HX-Redirect on 200 for htmx, 303 otherwise."""
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": url})
        return RedirectResponse(url, status_code=303)

    def render(
        self,
        request: Request,
        template: str,
        context: Mapping[str, Any] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        full_context: dict[str, Any] = {
            "admin": self,
            "request": request,
            "user": getattr(request.state, "hxadmin_user", None),
            "nav": build_nav(self, request),
        }
        if context:
            full_context.update(context)
        html = self.templates.get_template(template).render(full_context)
        return HTMLResponse(html, status_code=status_code)
