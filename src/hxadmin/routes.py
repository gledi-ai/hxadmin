from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import HTMLResponse

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin


def build_router(admin: "HxAdmin") -> APIRouter:
    router = APIRouter(dependencies=[Depends(admin.current_user)])

    @router.get("/", name="dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return admin.render(request, "dashboard.html")

    return router
