from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, with_parent
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from hxadmin.fields import Field, RelationField
from hxadmin.forms import (
    FormErrors,
    apply,
    form_relations,
    initial_values,
    parse_form,
    relabel,
    validate,
)
from hxadmin.query import apply_search, fetch_one, parse_list_params, run_list
from hxadmin.views import ModelView, pk_string_for

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
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        pk: str,
        relations: Sequence[str] = (),
    ) -> Any:
        obj = await fetch_one(session, view, view.get_query(request), pk, relations=relations)
        if obj is None:
            raise HTTPException(status_code=404)
        return obj

    def _render_form(
        request: Request,
        view: ModelView[Any],
        obj: Any | None,
        fields: Sequence[Field | RelationField],
        values: dict[str, Any],
        errors: FormErrors,
        *,
        created: bool,
        status_code: int = 200,
    ) -> HTMLResponse:
        list_url = admin.url(request, f"/{view.identity}/")
        if created:
            action_url = admin.url(request, f"/{view.identity}/new")
            cancel_url = list_url
        else:
            pk = view.pk_of(obj)
            action_url = admin.url(request, f"/{view.identity}/{pk}/edit")
            cancel_url = admin.url(request, f"/{view.identity}/{pk}") if view.can_view else list_url
        return admin.render(
            request,
            "form/_fields.html" if _is_htmx(request) else "form.html",
            {
                "view": view,
                "obj": obj,
                "fields": fields,
                "values": values,
                "errors": errors,
                "action_url": action_url,
                "cancel_url": cancel_url,
                "created": created,
            },
            status_code=status_code,
        )

    def _after_save(request: Request, view: ModelView[Any], pk: str, then: Any) -> str:
        if then == "another":
            return admin.url(request, f"/{view.identity}/new")
        if view.can_view:
            return admin.url(request, f"/{view.identity}/{pk}")
        return admin.url(request, f"/{view.identity}/")

    async def _save(
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        obj: Any,
        fields: Sequence[Field | RelationField],
        schema: type[BaseModel],
        *,
        created: bool,
    ) -> Response:
        form = await request.form()
        raw = parse_form(fields, form)
        values, errors = validate(schema, raw)
        if not errors:
            try:
                with session.no_autoflush:
                    await apply(session, view, obj, values, fields)
            except LookupError as exc:
                errors = FormErrors({str(exc): "Unknown selection."})
        if not errors:
            if created:
                session.add(obj)
            await view.on_save(request, session, obj, created=created)
            try:
                await session.flush()
                pk = view.pk_of(obj)
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if not created:
                    await session.refresh(obj)
                errors = FormErrors({}, form=str(exc.orig))
            else:
                return admin.redirect(request, _after_save(request, view, pk, form.get("_then")))
        shown = await relabel(admin, session, fields, raw)
        return _render_form(
            request,
            view,
            None if created else obj,
            fields,
            shown,
            errors,
            created=created,
            status_code=422,
        )

    @router.get("/{identity}/new", name="create", response_class=HTMLResponse)
    async def create_form(request: Request, identity: str) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.can_create:
            raise HTTPException(status_code=403)
        fields = view.writable_fields
        values = initial_values(admin, view, None, fields)
        return _render_form(request, view, None, fields, values, FormErrors(), created=True)

    @router.post("/{identity}/new")
    async def create(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if not view.can_create:
            raise HTTPException(status_code=403)
        return await _save(
            request,
            session,
            view,
            view.model(),
            view.writable_fields,
            view.create_schema,
            created=True,
        )

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

    @router.get("/{identity}/_lookup/{field}", name="lookup", response_class=HTMLResponse)
    async def lookup(
        request: Request,
        identity: str,
        field: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not (view.can_create or view.can_edit):
            raise HTTPException(status_code=403)
        relation = next((f for f in view.writable_fields if f.name == field), None)
        if not isinstance(relation, RelationField):
            raise HTTPException(status_code=404)
        q = request.query_params.get("q", "").strip()[:200]
        pk_columns = cast(Mapper[Any], inspect(relation.target)).primary_key
        target = admin.view_for(relation.target)
        if target is None:
            stmt = select(relation.target)
        else:
            if not target.is_accessible(request):
                raise HTTPException(status_code=403)
            stmt = apply_search(target.get_query(request), target, q)
        rows = (await session.scalars(stmt.order_by(*pk_columns).limit(20))).all()
        if target is None and q:
            rows = [row for row in rows if q.lower() in str(row).lower()]
        options = [(pk_string_for(relation.target, row), admin.display(row)) for row in rows]
        return admin.render(request, "form/_options.html", {"options": options, "q": q})

    @router.get("/{identity}/{pk}/edit", name="edit", response_class=HTMLResponse)
    async def edit_form(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.can_edit:
            raise HTTPException(status_code=403)
        fields = view.edit_fields
        obj = await _object(request, session, view, pk, form_relations(fields))
        values = initial_values(admin, view, obj, fields)
        return _render_form(request, view, obj, fields, values, FormErrors(), created=False)

    @router.post("/{identity}/{pk}/edit")
    async def edit(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if not view.can_edit:
            raise HTTPException(status_code=403)
        fields = view.edit_fields
        obj = await _object(request, session, view, pk, form_relations(fields))
        return await _save(request, session, view, obj, fields, view.edit_schema, created=False)

    @router.post("/{identity}/{pk}/delete", name="delete")
    async def delete(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if not view.can_delete:
            raise HTTPException(status_code=403)
        obj = await _object(request, session, view, pk)
        await view.on_delete(request, session, obj)
        await session.delete(obj)
        await session.commit()
        return admin.redirect(request, admin.url(request, f"/{view.identity}/"))

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
        scalar_fields = [
            f for f in view.detail_fields if not (isinstance(f, RelationField) and f.multiple)
        ]
        relations = [f.name for f in scalar_fields if isinstance(f, RelationField)]
        obj = await _object(request, session, view, pk, relations)
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
