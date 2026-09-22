from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import HTMLResponse

from hxadmin.query import parse_list_params, run_list
from hxadmin.views import ModelView

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _view(admin: "HxAdmin", request: Request, identity: str) -> ModelView[Any]:
    view = admin.views.get(identity)
    if view is None:
        raise HTTPException(status_code=404)
    if not view.is_accessible(request):
        raise HTTPException(status_code=403)
    return view


def build_router(admin: "HxAdmin") -> APIRouter:
    router = APIRouter(dependencies=[Depends(admin.current_user)])

    @router.get("/", name="dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return admin.render(request, "dashboard.html")

    @router.get("/{identity}/", name="list", response_class=HTMLResponse)
    async def list_view(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        params = parse_list_params(request, view)
        result = await run_list(session, view, view.get_query(request), params)
        return admin.render(
            request,
            "list/_table.html" if _is_htmx(request) else "list.html",
            {
                "view": view,
                "result": result,
                "base_url": admin.url(request, f"/{view.identity}/"),
                "push_url": True,
            },
        )

    return router
