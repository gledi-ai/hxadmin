import logging
from base64 import b64encode
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, cast
from urllib.parse import unquote, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, inspect, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, RelationshipProperty, with_parent
from starlette.datastructures import FormData, QueryParams
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from hxadmin.actions import Action, ActionResult
from hxadmin.audit import HISTORY_PAGE_SIZE, Snapshot, guard_commit, snapshot
from hxadmin.export import CSV_MEDIA_TYPE, export_response
from hxadmin.fields import Field, RelationField
from hxadmin.filters import relation_labels, visible_filters
from hxadmin.forms import (
    FormError,
    FormErrors,
    apply,
    build_schema,
    form_relations,
    initial_values,
    parse_form,
    relabel,
    resolve_relation,
    validate,
)
from hxadmin.import_csv import (
    MAX_ROWS,
    CsvImportError,
    CsvRow,
    import_payload,
    parse_import,
    template_bytes,
)
from hxadmin.inlines import (
    InlineChange,
    InlineGroup,
    inline_group,
    inline_groups,
    load_inlines,
    parse_inlines,
    related_form_fields,
)
from hxadmin.nav import build_dashboard, build_nav
from hxadmin.pk import INT64_MAX, fetch_by_pks, pk_string_for
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


@dataclass(frozen=True, slots=True)
class _RelatedCreate:
    parent: Any
    relationship: RelationshipProperty[Any]
    list_url: str
    parent_url: str
    inline: bool


def _bind_parent(obj: Any, parent: Any, relationship: RelationshipProperty[Any]) -> None:
    for parent_column, child_column in relationship.synchronize_pairs:
        parent_key = relationship.parent.get_property_by_column(parent_column).key
        child_key = relationship.mapper.get_property_by_column(child_column).key
        setattr(obj, child_key, getattr(parent, parent_key))
    if relationship.back_populates:
        setattr(obj, relationship.back_populates, parent)


async def _require_related(
    session: AsyncSession,
    view: ModelView[Any],
    pk: str,
    relation_filter: ColumnElement[bool],
    *,
    created: bool,
) -> None:
    belongs = select(1).select_from(view.model).where(*view.pk_clauses(pk), relation_filter)
    if await session.scalar(belongs) is None:
        record = "new record" if created else "record"
        raise FormError(f"The {record} must belong to this related collection.")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _view(admin: "HxAdmin", request: Request, identity: str) -> ModelView[Any]:
    view = admin.views.get(identity)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not view.is_accessible(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
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
    audit = admin._audit

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
            if isinstance(f, RelationField) and f.multiple and admin.can_reach(request, f.target)
        ]
        return {
            "view": view,
            "obj": obj,
            "scalar_fields": scalar_fields,
            "collections": collections,
            "active_collection": request.query_params.get("tab"),
            "history_url": (
                admin.url(request, f"/{view.identity}/_history/{view.pk_of(obj)}")
                if audit is not None and view.audit_fields and view.is_history_allowed(request)
                else None
            ),
            "back_url": _list_return_url(request, admin.url(request, f"/{view.identity}/")),
        }

    def _declared(view: ModelView[Any], name: str, request: Request, *, bulk: bool) -> Action:
        declared = view.actions.get(name)
        if declared is None or declared.bulk is not bulk:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if declared.method != request.method:
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": declared.method}
            )
        if not view.is_action_allowed(request, name):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return declared

    async def _action_input(request: Request) -> FormData | QueryParams:
        return await request.form() if request.method == "POST" else request.query_params

    async def _invoke_action(
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        declared: Action,
        target: Any,
    ) -> Any:
        handler = view.action_handler(declared.name)
        if audit is None or not declared.audit:
            return await handler(request, session, target)

        rows = target if declared.bulk else (target,)
        fields = view.audit_fields
        with guard_commit(session, operation="an audited action"):
            actor_id = await session.run_sync(lambda _: audit.actor_id(request.state.hxadmin_user))
            originals = await session.run_sync(
                lambda _: [(obj, view.pk_of(obj), snapshot(obj, fields)) for obj in rows]
            )
            result = await handler(request, session, target)
            if not isinstance(result, ActionResult):
                return result
            await session.flush()
            for obj, key, before in originals:
                if not inspect(obj).persistent:
                    raise ValueError("An audited action must keep its target rows")
                await session.refresh(obj, attribute_names=fields)
                if await session.run_sync(lambda _, record: view.pk_of(record), obj) != key:
                    raise ValueError("An audited action must keep its target primary keys")
                await audit.record(
                    session,
                    actor_id=actor_id,
                    identity=view.identity,
                    key=key,
                    operation="update",
                    before=before,
                    after=snapshot(obj, fields),
                    action_name=declared.name,
                )
        return result

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
            result = await _invoke_action(request, session, view, declared, target)
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
            if not view.allows_operation(request, "view"):
                return admin.redirect(request, list_url, toast=result.toast)
            context = await _detail_context(request, session, view, detail_pk)
            if context is None:
                return admin.redirect(request, list_url, toast=result.toast)
            response: Response = admin.render(request, "hxadmin/detail/_panel.html", context)
        else:
            current = QueryParams(urlsplit(request.headers.get("HX-Current-URL", "")).query)
            context = await _list_context(request, session, view, current)
            response = admin.render(request, "hxadmin/list/_table.html", context)
        if result.toast is not None:
            response.headers["HX-Trigger"] = hx_trigger(result.toast)
        return response

    @router.get("/", name="dashboard", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        groups = await build_dashboard(admin, request, session)
        return admin.render(request, "hxadmin/dashboard.html", {"dashboard": groups})

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
                        if view.allows_operation(request, "view")
                        else f"{list_url}?{urlencode({'q': q})}",
                    )
                    for row, label in zip(rows, labels, strict=True)
                ]
                records.append((view, hits))
        return admin.render(
            request, "hxadmin/_palette.html", {"q": q, "go_to": go_to, "records": records}
        )

    @router.get("/{identity}/", name="list", response_class=HTMLResponse)
    async def list_view(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        htmx = _is_htmx(request)
        context = await _list_context(request, session, view, panel=not htmx)
        return admin.render(
            request, "hxadmin/list/_table.html" if htmx else "hxadmin/list.html", context
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
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
        related_create: _RelatedCreate | None = None,
        inlines: Sequence[InlineGroup] = (),
        status_code: int = status.HTTP_200_OK,
    ) -> HTMLResponse:
        list_url = admin.url(request, f"/{view.identity}/")
        if related_create is not None:
            action_url = f"{related_create.list_url}/new"
            cancel_url = related_create.parent_url
        elif created:
            action_url = admin.url(request, f"/{view.identity}/new")
            cancel_url = list_url
        else:
            pk = view.pk_of(obj)
            action_url = admin.url(request, f"/{view.identity}/{pk}/edit")
            cancel_url = (
                admin.url(request, f"/{view.identity}/{pk}")
                if view.allows_operation(request, "view")
                else list_url
            )
        return admin.render(
            request,
            "hxadmin/form/_fields.html" if _is_htmx(request) else "hxadmin/form.html",
            {
                "view": view,
                "obj": obj,
                "fields": fields,
                "values": values,
                "errors": errors,
                "action_url": action_url,
                "cancel_url": cancel_url,
                "created": created,
                "inlines": inlines,
                "related_create": related_create is not None,
                "inline_related_url": (
                    related_create.list_url
                    if related_create is not None and related_create.inline
                    else None
                ),
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

    async def _audit_save(
        session: AsyncSession,
        view: ModelView[Any],
        obj: Any,
        pk: str,
        actor_id: str | None,
        before: Snapshot,
        *,
        created: bool,
    ) -> None:
        if audit is not None and actor_id is not None:
            await session.refresh(obj, attribute_names=view.audit_fields)
            await audit.record(
                session,
                actor_id=actor_id,
                identity=view.identity,
                key=pk,
                operation="create" if created else "update",
                before=before,
                after=snapshot(obj, view.audit_fields),
            )

    def _after_save(request: Request, view: ModelView[Any], pk: str, then: Any) -> str:
        if then == "another" and view.allows_operation(request, "create"):
            return admin.url(request, f"/{view.identity}/new")
        if view.allows_operation(request, "view"):
            return admin.url(request, f"/{view.identity}/{pk}")
        return _list_return_url(request, admin.url(request, f"/{view.identity}/"))

    async def _save_inline(
        request: Request, session: AsyncSession, parent: Any, change: InlineChange
    ) -> None:
        group, row = change.group, change.row
        view = group.view
        created = row.pk is None
        obj = view.model() if created else row.obj
        before: Snapshot = {}
        actor_id = None
        if audit is not None and view.audit_fields:
            actor_id = await session.run_sync(lambda _: audit.actor_id(request.state.hxadmin_user))
            if not created:
                before = await session.run_sync(lambda _: snapshot(obj, view.audit_fields))
        try:
            await apply(admin, request, session, view, obj, change.values, row.fields)
        except LookupError as exc:
            raise FormError("Unknown selection.", field=str(exc)) from exc
        if created:
            session.add(obj)
            await session.run_sync(lambda _: _bind_parent(obj, parent, group.relationship))
        await view.on_save(request, session, obj, created=created)
        await session.flush()
        pk = view.pk_of(obj)
        await _require_related(
            session,
            view,
            pk,
            with_parent(parent, group.relationship.class_attribute),
            created=created,
        )
        await _audit_save(session, view, obj, pk, actor_id, before, created=created)

    async def _save(
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        obj: Any,
        fields: Sequence[Field | RelationField],
        schema: type[BaseModel],
        *,
        created: bool,
        related_create: _RelatedCreate | None = None,
    ) -> Response:
        form = await request.form()
        inlines = []
        if related_create is None:
            inlines = (
                inline_groups(admin, request, view, created=True)
                if created
                else await load_inlines(admin, request, session, view, obj)
            )
        changes = parse_inlines(admin, inlines, form) if view.form_inlines else []
        raw = parse_form(fields, form, created=created)
        values, errors = validate(schema, raw)
        inline_errors = any(change.row.errors for change in changes)
        before: Snapshot = {}
        actor_id = None
        if not errors and not inline_errors:
            if audit is not None and view.audit_fields:
                actor_id = await session.run_sync(
                    lambda _: audit.actor_id(request.state.hxadmin_user)
                )
                if not created:
                    before = await session.run_sync(lambda _: snapshot(obj, view.audit_fields))
            try:
                await apply(admin, request, session, view, obj, values, fields)
            except LookupError as exc:
                if not created:
                    await _rollback(request, session)
                    await session.refresh(obj)
                errors = FormErrors({str(exc): "Unknown selection."})
        if not errors and not inline_errors:
            if created:
                session.add(obj)
            current_change = None
            try:
                if related_create is not None:
                    await session.run_sync(
                        lambda _: _bind_parent(
                            obj, related_create.parent, related_create.relationship
                        )
                    )
                with (
                    guard_commit(session, operation="an inline save") if changes else nullcontext()
                ):
                    await view.on_save(request, session, obj, created=created)
                    await session.flush()
                    for current_change in changes:
                        await _save_inline(request, session, obj, current_change)
                current_change = None
                pk = view.pk_of(obj)
                listing = None
                if related_create is not None:
                    relation_filter = with_parent(
                        related_create.parent, related_create.relationship.class_attribute
                    )
                    await _require_related(session, view, pk, relation_filter, created=True)
                    if related_create.inline:
                        listing = await _related_table(
                            request,
                            session,
                            view,
                            relation_filter,
                            related_create.list_url,
                            can_create=True,
                        )
                await _audit_save(session, view, obj, pk, actor_id, before, created=created)
                label = await session.run_sync(lambda _: view.display(obj))
                url = (
                    related_create.parent_url
                    if related_create is not None
                    else _after_save(request, view, pk, form.get("_then"))
                )
                await session.commit()
            except (IntegrityError, DataError, FormError) as exc:
                await _rollback(request, session)
                if not created:
                    await session.refresh(obj)
                if current_change is None:
                    errors = _save_errors(exc, fields)
                else:
                    current_change.row.errors = _save_errors(exc, current_change.row.fields)
            except Exception:
                await _rollback(request, session)
                raise
            else:
                done = Toast(f"{view.name} “{label}” {'created' if created else 'saved'}.")
                if listing is not None:
                    listing.headers["HX-Trigger"] = hx_trigger(done)
                    return listing
                return admin.redirect(request, url, toast=done)
        shown = await relabel(admin, request, session, fields, raw)
        for change in changes:
            row = change.row
            row.values.update(await relabel(admin, request, session, row.fields, change.raw))
        return _render_form(
            request,
            view,
            None if created else obj,
            fields,
            shown,
            errors,
            created=created,
            related_create=related_create,
            inlines=inlines,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @router.get("/{identity}/new", name="create", response_class=HTMLResponse)
    async def create_form(request: Request, identity: str) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.allows_operation(request, "create"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        fields = view.writable_fields
        values = initial_values(admin, view, None, fields)
        inlines = inline_groups(admin, request, view, created=True)
        return _render_form(
            request, view, None, fields, values, FormErrors(), created=True, inlines=inlines
        )

    @router.post("/{identity}/new")
    async def create(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if not view.allows_operation(request, "create"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return await _save(
            request,
            session,
            view,
            view.model(),
            view.writable_fields,
            view.create_schema,
            created=True,
        )

    def _import_view(request: Request, identity: str) -> ModelView[Any]:
        view = _view(admin, request, identity)
        if not view.allows_import(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return view

    def _render_import(
        request: Request,
        view: ModelView[Any],
        *,
        columns: Sequence[str] = (),
        rows: Sequence[CsvRow] = (),
        payload: str = "",
        error: str = "",
    ) -> HTMLResponse:
        invalid = bool(error) or any(row.errors for row in rows)
        response = admin.render(
            request,
            "hxadmin/import.html",
            {
                "view": view,
                "columns": columns,
                "rows": rows,
                "payload": payload,
                "error": error,
                "max_rows": MAX_ROWS,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if invalid else status.HTTP_200_OK,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/{identity}/_import/template", name="import_template")
    async def import_template(request: Request, identity: str) -> Response:
        view = _import_view(request, identity)
        return Response(
            template_bytes(view.import_columns),
            media_type=CSV_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="import-template.csv"'},
        )

    @router.get("/{identity}/_import/upload", name="import_form", response_class=HTMLResponse)
    async def import_form(request: Request, identity: str) -> HTMLResponse:
        return _render_import(request, _import_view(request, identity))

    async def _commit_import(
        request: Request,
        session: AsyncSession,
        view: ModelView[Any],
        columns: list[str],
        rows: list[CsvRow],
    ) -> Response:
        actor_id = None
        if audit is not None and view.audit_fields:
            actor_id = await session.run_sync(lambda _: audit.actor_id(request.state.hxadmin_user))
        active_row: CsvRow | None = None
        committing = False
        try:
            with guard_commit(session, operation="a CSV import"):
                for row in rows:
                    active_row = row
                    obj = view.model()
                    try:
                        await apply(
                            admin, request, session, view, obj, row.values, view.import_fields
                        )
                    except LookupError as exc:
                        raise FormError("Unknown selection.", field=str(exc)) from exc
                    session.add(obj)
                    transaction = session.get_transaction()
                    await view.on_save(request, session, obj, created=True)
                    if session.get_transaction() is not transaction:
                        raise RuntimeError("Leave transaction control for CSV imports to hxadmin")
                    await session.flush()
                    await _audit_save(
                        session, view, obj, view.pk_of(obj), actor_id, {}, created=True
                    )
            committing = True
            await session.commit()
        except (IntegrityError, DataError, FormError) as exc:
            await _rollback(request, session)
            errors = _save_errors(exc, view.writable_fields)
            message = "No records were imported."
            if active_row is not None and not committing:
                active_row.errors = errors
            elif errors.form:
                message = errors.form
            return _render_import(
                request,
                view,
                columns=columns,
                rows=rows,
                error=message,
            )
        except Exception:
            await _rollback(request, session)
            raise
        count = len(rows)
        return admin.redirect(
            request,
            admin.url(request, f"/{view.identity}/"),
            toast=Toast(f"Imported {count} {'record' if count == 1 else 'records'}."),
        )

    async def _handle_import(
        request: Request, identity: str, session: AsyncSession, *, confirm: bool
    ) -> Response:
        view = _import_view(request, identity)
        try:
            data = await import_payload(request, confirm=confirm)
            columns, rows = parse_import(view, data)
        except CsvImportError as exc:
            return _render_import(request, view, error=str(exc))
        if confirm:
            if any(row.errors for row in rows):
                return _render_import(request, view, columns=columns, rows=rows)
            return await _commit_import(request, session, view, columns, rows)

        relations = [field for field in view.import_fields if isinstance(field, RelationField)]
        for row in rows:
            for field in relations:
                if field.name in row.values:
                    try:
                        await resolve_relation(
                            admin, request, session, field, row.values[field.name]
                        )
                    except LookupError:
                        row.errors.fields[field.name] = "Unknown selection."
        payload = "" if any(row.errors for row in rows) else b64encode(data).decode("ascii")
        return _render_import(request, view, columns=columns, rows=rows, payload=payload)

    @router.post("/{identity}/_import/upload", name="import_preview")
    async def import_preview(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        return await _handle_import(request, identity, session, confirm=False)

    @router.post("/{identity}/_import/confirm", name="import_confirm")
    async def import_confirm(
        request: Request,
        identity: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        return await _handle_import(request, identity, session, confirm=True)

    def _related_field(request: Request, view: ModelView[Any], rel: str) -> RelationField:
        if not view.allows_operation(request, "view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        field = next((f for f in view.detail_fields if f.name == rel), None)
        if not isinstance(field, RelationField) or not field.multiple:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return field

    async def _related_table(
        request: Request,
        session: AsyncSession,
        target: ModelView[Any],
        relation_filter: ColumnElement[bool],
        base_url: str,
        *,
        can_create: bool,
    ) -> HTMLResponse:
        stmt = target.get_query(request).where(relation_filter)
        params = parse_list_params(request, target)
        result = await run_list(session, target, stmt, params)
        return admin.render(
            request,
            "hxadmin/list/_table.html",
            {
                "view": target,
                "result": result,
                "base_url": base_url,
                "push_url": False,
                "related_create_url": f"{base_url}/new" if can_create else None,
            },
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
        field = _related_field(request, view, rel)
        obj = await _object(request, session, view, pk)
        base_url = admin.url(request, f"/{view.identity}/_related/{pk}/{rel}")
        relation_filter = with_parent(obj, getattr(view.model, rel))
        target = admin.view_for(field.target)
        if target is None:
            stmt = select(field.target).where(relation_filter)
            rows = (await session.scalars(stmt.limit(100))).all()
            return admin.render(request, "hxadmin/detail/_related_plain.html", {"rows": rows})
        if not target.is_accessible(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return await _related_table(
            request,
            session,
            target,
            relation_filter,
            base_url,
            can_create=rel in view.related_create and target.allows_operation(request, "create"),
        )

    @router.get("/{identity}/_related/{pk}/{rel}/new", response_class=HTMLResponse)
    @router.post("/{identity}/_related/{pk}/{rel}/new")
    async def create_related(
        request: Request,
        identity: str,
        pk: str,
        rel: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        field = _related_field(request, view, rel)
        target = admin.view_for(field.target)
        if rel not in view.related_create or target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if not target.is_accessible(request) or not target.allows_operation(request, "create"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        parent = await _object(request, session, view, pk)
        relationship = inspect(view.model, raiseerr=True).relationships[rel]
        fields = related_form_fields(target.writable_fields, relationship)
        context = _RelatedCreate(
            parent,
            relationship,
            admin.url(request, f"/{identity}/_related/{pk}/{rel}"),
            admin.url(request, f"/{identity}/{pk}?{urlencode({'tab': rel})}"),
            _is_htmx(request)
            and unquote(request.headers.get("HX-Target", "").removeprefix("div#"))
            == f"related-panel-{rel}",
        )
        if request.method == "GET":
            values = initial_values(admin, target, None, fields)
            return _render_form(
                request,
                target,
                None,
                fields,
                values,
                FormErrors(),
                created=True,
                related_create=context,
            )
        return await _save(
            request,
            session,
            target,
            target.model(),
            fields,
            build_schema(target.model, fields),
            created=True,
            related_create=context,
        )

    @router.get("/{identity}/_inline/{rel}/new", response_class=HTMLResponse)
    async def new_inline_row(request: Request, identity: str, rel: str) -> HTMLResponse:
        view = _view(admin, request, identity)
        if rel not in view.form_inlines:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        group = inline_group(admin, request, view, rel)
        if (
            group is None
            or not group.can_create
            or not (
                view.allows_operation(request, "create") or view.allows_operation(request, "edit")
            )
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        response = admin.render(
            request,
            "hxadmin/form/_inline_row.html",
            {"group": group, "row": group.new_row(admin), "focus_new": True},
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/{identity}/_history/{pk}", name="history", response_class=HTMLResponse)
    async def history(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
        before: Annotated[int | None, Query(gt=0, le=INT64_MAX)] = None,
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.allows_operation(request, "view") or not view.is_history_allowed(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if audit is None or not view.audit_fields:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        obj = await _object(request, session, view, pk)
        key = view.pk_of(obj)
        entries = await audit.history(session, view.identity, key, before=before)
        url = admin.url(request, f"/{identity}/_history/{key}")
        next_url = (
            f"{url}?before={entries[HISTORY_PAGE_SIZE - 1]['id']}"
            if len(entries) > HISTORY_PAGE_SIZE
            else None
        )
        return admin.render(
            request,
            "hxadmin/detail/_history.html",
            {"entries": entries[:HISTORY_PAGE_SIZE], "next_url": next_url, "view": view},
        )

    @router.get("/{identity}/_lookup/{field}", name="lookup", response_class=HTMLResponse)
    async def lookup(
        request: Request,
        identity: str,
        field: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not (view.allows_operation(request, "create") or view.allows_operation(request, "edit")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        relation = next((f for f in view.writable_fields if f.name == field), None)
        if not isinstance(relation, RelationField):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        q = request.query_params.get("q", "").strip()[:200]
        pk_columns = cast(Mapper[Any], inspect(relation.target)).primary_key
        target = admin.view_for(relation.target)
        if target is None:
            stmt = select(relation.target)
        else:
            if not target.is_accessible(request):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
            stmt = apply_search(target.get_query(request), target, q)
        stmt = stmt.order_by(*pk_columns)
        if q and (target is None or not target.searchable):
            rows = await _display_matches(session, stmt, q)
        else:
            rows = (await session.scalars(stmt.limit(LOOKUP_LIMIT))).all()
        options = [(pk_string_for(relation.target, row), admin.display(row)) for row in rows]
        return admin.render(request, "hxadmin/form/_options.html", {"options": options, "q": q})

    @router.get("/{identity}/_export/{fmt}", name="export")
    async def export(
        request: Request,
        identity: str,
        fmt: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if fmt not in view.export_formats:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if not view.allows_operation(request, "export"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
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
        from_detail = view.allows_operation(request, "view") and data.get("_from") != "list"
        return await _run_action(request, session, view, declared, obj, pk if from_detail else None)

    @router.get("/{identity}/{pk}/edit", name="edit", response_class=HTMLResponse)
    async def edit_form(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> HTMLResponse:
        view = _view(admin, request, identity)
        if not view.allows_operation(request, "edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        fields = view.edit_fields
        obj = await _object(request, session, view, pk, form_relations(fields))
        values = initial_values(admin, view, obj, fields)
        inlines = await load_inlines(admin, request, session, view, obj)
        return _render_form(
            request, view, obj, fields, values, FormErrors(), created=False, inlines=inlines
        )

    @router.post("/{identity}/{pk}/edit")
    async def edit(
        request: Request,
        identity: str,
        pk: str,
        session: Annotated[AsyncSession, Depends(admin.current_session)],
    ) -> Response:
        view = _view(admin, request, identity)
        if not view.allows_operation(request, "edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
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
        if not view.allows_operation(request, "delete"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        obj = await _object(request, session, view, pk)
        label = await session.run_sync(lambda _: view.display(obj))
        audit_context = None
        try:
            if audit is not None and view.audit_fields:
                actor_id = await session.run_sync(
                    lambda _: audit.actor_id(request.state.hxadmin_user)
                )
                before = await session.run_sync(lambda _: snapshot(obj, view.audit_fields))
                audit_context = actor_id, view.pk_of(obj), before
            await view.on_delete(request, session, obj)
            await session.delete(obj)
            if audit is not None and audit_context is not None:
                actor_id, record_key, before = audit_context
                await session.flush()
                await audit.record(
                    session,
                    actor_id=actor_id,
                    identity=view.identity,
                    key=record_key,
                    operation="delete",
                    before=before,
                    after={},
                )
            await session.commit()
        except IntegrityError as exc:
            await _rollback(request, session)
            logger.warning("Delete rejected by a database constraint: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
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
        if not view.allows_operation(request, "view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        context = await _detail_context(request, session, view, pk)
        if context is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return admin.render(
            request,
            "hxadmin/detail/_panel.html" if _is_htmx(request) else "hxadmin/detail.html",
            context,
        )

    return router
