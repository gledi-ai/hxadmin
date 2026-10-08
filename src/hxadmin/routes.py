import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, cast
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, inspect, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, with_parent
from starlette.datastructures import FormData, QueryParams
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from hxadmin.actions import Action, ActionResult
from hxadmin.export import export_response
from hxadmin.fields import Field, RelationField
from hxadmin.filters import relation_labels, visible_filters
from hxadmin.forms import (
    FormError,
    FormErrors,
    apply,
    form_relations,
    initial_values,
    parse_form,
    relabel,
    validate,
)
from hxadmin.nav import build_dashboard, build_nav
from hxadmin.pk import fetch_by_pks, pk_string_for
from hxadmin.query import (
    apply_search,
    count_rows,
    fetch_one,
    list_statement,
    parse_list_params,
    run_list,
    with_relations,
)
from hxadmin.toasts import Toast, hx_trigger
from hxadmin.users import refresh_user
from hxadmin.views import ModelView

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin

logger = logging.getLogger("hxadmin")

CONFLICT_MESSAGE = (
    "Couldn't save: this conflicts with existing data (for example a duplicate value)."
)
LOOKUP_LIMIT = 20
LOOKUP_SCAN_MAX = 2000


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _view(admin: "HxAdmin", request: Request, identity: str) -> ModelView[Any]:
    view = admin.views.get(identity)
    if view is None:
        raise HTTPException(status_code=404)
    if not view.is_accessible(request):
        raise HTTPException(status_code=403)
    return view


def _palette_views(admin: "HxAdmin") -> list[ModelView[Any]]:
    """Views in nav order (grouped by category, like `build_nav`), ignoring pages."""
    groups: dict[str | None, list[ModelView[Any]]] = {None: []}
    for view in admin.views.values():
        groups.setdefault(view.category, []).append(view)
    return [view for views in groups.values() for view in views]


def _toast_only(status_code: int, toast: Toast) -> Response:
    return Response(
        status_code=status_code,
        headers={"HX-Trigger": hx_trigger(toast), "HX-Reswap": "none"},
    )


async def _rollback(request: Request, session: AsyncSession) -> None:
    await session.rollback()
    await refresh_user(request, session)


def _list_return_url(request: Request, list_url: str) -> str:
    """`list_url` with the query of the `Referer` when that is the same list (search, sort, page).

    Only the query string is reused, so a foreign referer cannot redirect elsewhere.
    """
    referer = urlsplit(request.headers.get("referer", ""))
    if referer.path == list_url and referer.query:
        return f"{list_url}?{referer.query}"
    return list_url


def build_router(admin: "HxAdmin") -> APIRouter:
    router = APIRouter(dependencies=[Depends(admin.current_user)])

    async def _display_matches(session: AsyncSession, stmt: Select[Any], q: str) -> list[Any]:
        """Up to `LOOKUP_LIMIT` rows whose display contains `q`, scanning `LOOKUP_SCAN_MAX` rows."""
        needle = q.lower()
        matches: list[Any] = []
        scan = stmt.limit(LOOKUP_SCAN_MAX).execution_options(yield_per=200)
        result = await session.stream_scalars(scan)
        try:
            async for row in result:
                if needle in admin.display(row).lower():
                    matches.append(row)
                    if len(matches) == LOOKUP_LIMIT:
                        break
        finally:
            await result.close()
        return matches

    async def _list_context(
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        query: QueryParams | None = None,
        *,
        panel: bool = False,
    ) -> dict[str, Any]:
        """List template context for `query` (default: the request's).

        `panel` also loads the filter panel's relation options.
        """
        filters = visible_filters(admin, request, view.filters)
        params = parse_list_params(request, view, query=query, filters=filters)
        result = await run_list(session, view, view.get_query(request), params)
        labels = await relation_labels(
            admin, request, session, filters, params.filters, with_options=panel
        )
        return {
            "view": view,
            "result": result,
            "base_url": admin.url(request, f"/{view.identity}/"),
            "push_url": True,
            "filters": filters,
            "filter_options": labels,
            "htmx": _is_htmx(request),
        }

    async def _detail_context(
        request: Request, session: AsyncSession, view: ModelView[Any], pk: str
    ) -> dict[str, Any] | None:
        scalar_fields = [
            f for f in view.detail_fields if not (isinstance(f, RelationField) and f.multiple)
        ]
        relations = [f.name for f in scalar_fields if isinstance(f, RelationField)]
        if not view.detail_columns:
            # FK columns whose relation is also shown are redundant next to the relation link.
            shown_fk_columns = {
                name for f in scalar_fields if isinstance(f, RelationField) for name in f.fk_columns
            }
            scalar_fields = [
                f
                for f in scalar_fields
                if not (isinstance(f, Field) and f.name in shown_fk_columns)
            ]
        obj = await fetch_one(session, view, view.get_query(request), pk, relations=relations)
        if obj is None:
            return None
        collections = [
            (f, admin.url(request, f"/{view.identity}/_related/{pk}/{f.name}"))
            for f in view.detail_fields
            if isinstance(f, RelationField) and f.multiple
        ]
        return {
            "view": view,
            "obj": obj,
            "scalar_fields": scalar_fields,
            "collections": collections,
            "back_url": _list_return_url(request, admin.url(request, f"/{view.identity}/")),
        }

    def _declared(view: ModelView[Any], name: str, request: Request, *, bulk: bool) -> Action:
        declared = view.actions.get(name)
        if declared is None or declared.bulk is not bulk:
            raise HTTPException(status_code=404)
        if declared.method != request.method:
            raise HTTPException(status_code=405, headers={"Allow": declared.method})
        if not view.is_action_allowed(request, name):
            raise HTTPException(status_code=403)
        return declared

    async def _action_input(request: Request) -> FormData | QueryParams:
        return await request.form() if request.method == "POST" else request.query_params

    async def _run_action(
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        declared: Action,
        target: Any,
        detail_pk: str | None,
    ) -> Response:
        """Run a handler, commit or roll back, and answer for htmx or a native submit.

        `detail_pk` is set when the detail panel of that row is the view to re-render;
        otherwise the list (as shown at `HX-Current-URL`) is.
        """
        list_url = admin.url(request, f"/{view.identity}/")
        back = _list_return_url(request, list_url)
        if detail_pk is not None:
            back = admin.url(request, f"/{view.identity}/{detail_pk}")
        try:
            result = await view.action_handler(declared.name)(request, session, target)
            if not isinstance(result, ActionResult):
                raise TypeError(f"expected ActionResult, got {type(result).__name__}")
            await session.commit()
        except StarletteHTTPException:
            await _rollback(request, session)
            raise
        except Exception:
            await _rollback(request, session)
            logger.exception("Action %r on %r failed", declared.name, view.identity)
            failed = Toast(f"{declared.label} failed.", "error")
            if _is_htmx(request):
                return _toast_only(500, failed)
            return admin.redirect(request, back, toast=failed)
        if result.raw is not None:
            return result.raw
        if result.url is not None:
            return admin.redirect(request, result.url)
        if not _is_htmx(request):
            return admin.redirect(request, back, toast=result.toast)
        session.expire_all()
        await refresh_user(request, session)
        if detail_pk is not None:
            context = await _detail_context(request, session, view, detail_pk)
            if context is None:
                return admin.redirect(request, list_url, toast=result.toast)
            response: Response = admin.render(request, "detail/_panel.html", context)
        else:
            current = QueryParams(urlsplit(request.headers.get("HX-Current-URL", "")).query)
            context = await _list_context(request, session, view, current)
            response = admin.render(request, "list/_table.html", context)
        if result.toast is not None:
            response.headers["HX-Trigger"] = hx_trigger(result.toast)
        return response

    @router.get("/", name="dashboard", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        groups = await build_dashboard(admin, request, session)
        return admin.render(request, "dashboard.html", {"dashboard": groups})

    @router.get("/_palette", name="palette", response_class=HTMLResponse)
    async def palette(
        request: Request,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        go_to = [
            item
            for group in build_nav(admin, request)
            for item in group.items
            if not q or q.lower() in item.label.lower()
        ]
        records: list[tuple[ModelView[Any], list[tuple[str, str]]]] = []
        if q:
            views = [
                view
                for view in _palette_views(admin)
                if view.searchable and view.is_visible(request) and view.is_accessible(request)
            ][:8]
            for view in views:
                stmt = apply_search(view.get_query(request), view, q).limit(5)
                rows = (await session.scalars(stmt)).all()
                if not rows:
                    continue
                labels = await session.run_sync(
                    lambda _, view=view, rows=rows: [view.display(row) for row in rows]
                )
                list_url = admin.url(request, f"/{view.identity}/")
                hits = [
                    (
                        label,
                        admin.url(request, f"/{view.identity}/{view.pk_of(row)}")
                        if view.can_view
                        else f"{list_url}?{urlencode({'q': q})}",
                    )
                    for row, label in zip(rows, labels, strict=True)
                ]
                records.append((view, hits))
        return admin.render(request, "_palette.html", {"q": q, "go_to": go_to, "records": records})

    @router.get("/{identity}/", name="list", response_class=HTMLResponse)
    async def list_view(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        htmx = _is_htmx(request)
        context = await _list_context(request, session, view, panel=not htmx)
        return admin.render(request, "list/_table.html" if htmx else "list.html", context)

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

    def _save_errors(
        exc: IntegrityError | DataError | FormError, fields: Sequence[Field | RelationField]
    ) -> FormErrors:
        if isinstance(exc, IntegrityError):
            logger.warning("Save rejected by a database constraint: %s", exc.orig)
            return FormErrors({}, form=CONFLICT_MESSAGE)
        if isinstance(exc, DataError):
            logger.warning("Save rejected by the database: %s", exc.orig)
            return FormErrors({}, form="Couldn't save: the database rejected a value.")
        if exc.field is not None and any(f.name == exc.field for f in fields):
            return FormErrors({exc.field: exc.message})
        return FormErrors({}, form=exc.message)

    def _after_save(request: Request, view: ModelView[Any], pk: str, then: Any) -> str:
        if then == "another":
            return admin.url(request, f"/{view.identity}/new")
        if view.can_view:
            return admin.url(request, f"/{view.identity}/{pk}")
        return _list_return_url(request, admin.url(request, f"/{view.identity}/"))

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
        raw = parse_form(fields, form, created=created)
        values, errors = validate(schema, raw)
        if not errors:
            try:
                await apply(admin, request, session, view, obj, values, fields)
            except LookupError as exc:
                if not created:
                    await _rollback(request, session)
                    await session.refresh(obj)
                errors = FormErrors({str(exc): "Unknown selection."})
        if not errors:
            if created:
                session.add(obj)
            try:
                await view.on_save(request, session, obj, created=created)
                await session.flush()
                pk = view.pk_of(obj)
                label = await session.run_sync(lambda _: view.display(obj))
                await session.commit()
            except (IntegrityError, DataError, FormError) as exc:
                await _rollback(request, session)
                if not created:
                    await session.refresh(obj)
                errors = _save_errors(exc, fields)
            except Exception:
                await _rollback(request, session)
                raise
            else:
                done = Toast(f"{view.name} “{label}” {'created' if created else 'saved'}.")
                url = _after_save(request, view, pk, form.get("_then"))
                return admin.redirect(request, url, toast=done)
        shown = await relabel(admin, request, session, fields, raw)
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
        stmt = stmt.order_by(*pk_columns)
        if q and (target is None or not target.searchable):
            rows = await _display_matches(session, stmt, q)
        else:
            rows = (await session.scalars(stmt.limit(LOOKUP_LIMIT))).all()
        options = [(pk_string_for(relation.target, row), admin.display(row)) for row in rows]
        return admin.render(request, "form/_options.html", {"options": options, "q": q})

    @router.get("/{identity}/_export/{fmt}", name="export")
    async def export(
        request: Request,
        identity: str,
        fmt: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if fmt not in view.export_formats:
            raise HTTPException(status_code=404)
        stmt = view.get_query(request)
        pks = list(dict.fromkeys(request.query_params.getlist("pks")))
        if pks:
            loaded = with_relations(stmt, view.model, view.export_fields)
            rows = await fetch_by_pks(session, view.model, pks, stmt=loaded)
            return await export_response(admin, view, fmt, rows)
        filters = visible_filters(admin, request, view.filters)
        params = parse_list_params(request, view, filters=filters)
        stmt = list_statement(view, stmt, params)
        limit = view.export_max_rows
        if limit is not None and await count_rows(session, stmt) > limit:
            list_url = admin.url(request, f"/{view.identity}/")
            query = request.url.query
            too_many = Toast(
                f"Export is limited to {limit:,} rows; narrow the search or filters.", "warning"
            )
            return admin.redirect(
                request, f"{list_url}?{query}" if query else list_url, toast=too_many
            )
        loaded = with_relations(stmt, view.model, view.export_fields)
        rows = (await session.scalars(loaded)).all()
        return await export_response(admin, view, fmt, rows)

    @router.api_route("/{identity}/action/{name}", methods=["GET", "POST"], name="bulk_action")
    async def bulk_action(
        request: Request,
        identity: str,
        name: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        declared = _declared(view, name, request, bulk=True)
        data = await _action_input(request)
        pks = list(dict.fromkeys(v for v in data.getlist("pks") if isinstance(v, str)))
        objs = await fetch_by_pks(session, view.model, pks, stmt=view.get_query(request))
        if not objs:
            empty = Toast("No rows selected.", "warning")
            if _is_htmx(request):
                return _toast_only(400, empty)
            list_url = admin.url(request, f"/{view.identity}/")
            return admin.redirect(request, _list_return_url(request, list_url), toast=empty)
        return await _run_action(request, session, view, declared, objs, None)

    @router.api_route("/{identity}/{pk}/action/{name}", methods=["GET", "POST"], name="row_action")
    async def row_action(
        request: Request,
        identity: str,
        pk: str,
        name: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        declared = _declared(view, name, request, bulk=False)
        data = await _action_input(request)
        obj = await _object(request, session, view, pk)
        from_detail = view.can_view and data.get("_from") != "list"
        return await _run_action(request, session, view, declared, obj, pk if from_detail else None)

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
        label = await session.run_sync(lambda _: view.display(obj))
        try:
            await view.on_delete(request, session, obj)
            await session.delete(obj)
            await session.commit()
        except IntegrityError as exc:
            await _rollback(request, session)
            logger.warning("Delete rejected by a database constraint: %s", exc.orig)
            raise HTTPException(
                status_code=409,
                detail=f"Couldn't delete {view.name} “{label}”: other records still refer to it.",
            ) from None
        except Exception:
            await _rollback(request, session)
            raise
        deleted = Toast(f"{view.name} “{label}” deleted.")
        list_url = admin.url(request, f"/{view.identity}/")
        return admin.redirect(request, _list_return_url(request, list_url), toast=deleted)

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
        context = await _detail_context(request, session, view, pk)
        if context is None:
            raise HTTPException(status_code=404)
        return admin.render(
            request, "detail/_panel.html" if _is_htmx(request) else "detail.html", context
        )

    return router
