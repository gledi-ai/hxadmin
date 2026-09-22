from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import with_parent
from starlette.requests import Request
from starlette.responses import HTMLResponse

from hxadmin.fields import RelationField
from hxadmin.query import fetch_one, parse_list_params, run_list
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

    async def _object(
        request: Request, session: AsyncSession, view: ModelView[Any], pk: str
    ) -> Any:
        obj = await fetch_one(session, view, view.get_query(request), pk)
        if obj is None:
            raise HTTPException(status_code=404)
        return obj

    @router.get("/{identity}/_related/{pk}/{rel}", name="related", response_class=HTMLResponse)
    async def related(
        request: Request,
        identity: str,
        pk: str,
        rel: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.can_view:
            raise HTTPException(status_code=403)
        field = next((f for f in view.detail_fields if f.name == rel), None)
        if not isinstance(field, RelationField) or not field.multiple:
            raise HTTPException(status_code=404)
        obj = await _object(request, session, view, pk)
        base_url = admin.url(request, f"/{view.identity}/_related/{pk}/{rel}")
        target = admin.view_for(field.target)
        if target is None:
            stmt = select(field.target).where(with_parent(obj, getattr(view.model, rel)))
            rows = (await session.scalars(stmt.limit(100))).all()
            return admin.render(request, "detail/_related_plain.html", {"rows": rows})
        if not target.is_accessible(request):
            raise HTTPException(status_code=403)
        stmt = target.get_query(request).where(with_parent(obj, getattr(view.model, rel)))
        params = parse_list_params(request, target)
        result = await run_list(session, target, stmt, params)
        return admin.render(
            request,
            "list/_table.html",
            {"view": target, "result": result, "base_url": base_url, "push_url": False},
        )

    @router.get("/{identity}/{pk}", name="detail", response_class=HTMLResponse)
    async def detail(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.can_view:
            raise HTTPException(status_code=403)
        obj = await _object(request, session, view, pk)
        scalar_fields = [
            f for f in view.detail_fields if not (isinstance(f, RelationField) and f.multiple)
        ]
        collections = [
            (f, admin.url(request, f"/{view.identity}/_related/{pk}/{f.name}"))
            for f in view.detail_fields
            if isinstance(f, RelationField) and f.multiple
        ]
        return admin.render(
            request,
            "detail/_panel.html" if _is_htmx(request) else "detail.html",
            {
                "view": view,
                "obj": obj,
                "scalar_fields": scalar_fields,
                "collections": collections,
            },
        )

    return router
