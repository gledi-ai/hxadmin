from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import ceil
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import Select, String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import QueryParams
from starlette.requests import Request

from hxadmin.fields import Field, RelationField
from hxadmin.filters import Filter, FilterValue, apply_filters, escape_like, parse_filters
from hxadmin.views import ModelView, SortDir


@dataclass(frozen=True, slots=True)
class ListParams:
    q: str
    sort: str | None
    dir: SortDir
    page: int
    size: int
    filters: tuple[FilterValue, ...] = ()

    def filter_value(self, name: str) -> FilterValue:
        """The active value of filter `name`, or an empty one."""
        return next((v for v in self.filters if v.name == name), FilterValue(name))

    def qs(self, **changes: Any) -> str:
        merged = replace(self, **changes)
        pairs = [
            ("q", merged.q or None),
            *(pair for value in merged.filters for pair in value.pairs()),
            ("sort", merged.sort),
            ("dir", merged.dir),
            ("page", merged.page),
            ("size", merged.size),
        ]
        return urlencode([(k, v) for k, v in pairs if v is not None])


@dataclass(frozen=True, slots=True)
class ListResult:
    rows: Sequence[Any]
    total: int
    params: ListParams

    @property
    def pages(self) -> int:
        return max(1, ceil(self.total / self.params.size))

    @property
    def start(self) -> int:
        return 0 if self.total == 0 else (self.params.page - 1) * self.params.size + 1

    @property
    def end(self) -> int:
        return 0 if self.total == 0 else self.start + len(self.rows) - 1

    @property
    def has_prev(self) -> bool:
        return self.params.page > 1

    @property
    def has_next(self) -> bool:
        return self.params.page < self.pages


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def parse_list_params(
    request: Request,
    view: ModelView[Any],
    *,
    query: QueryParams | None = None,
    filters: Sequence[Filter] | None = None,
) -> ListParams:
    """List params from `query` (default: the request's query string); invalid values fall back.

    Only `filters` (default: all of the view's filters) are read.
    """
    source = request.query_params if query is None else query
    default_sort, default_dir = view.default_sort or (None, "asc")
    sort = source.get("sort")
    if sort not in view.sort_names:
        sort = default_sort
    raw_dir = source.get("dir")
    dir_: SortDir = raw_dir if raw_dir in ("asc", "desc") else default_dir
    size = _int(source.get("size"), view.page_size)
    if size not in view.page_size_options:
        size = view.page_size
    return ListParams(
        q=source.get("q", "").strip(),
        sort=sort,
        dir=dir_,
        page=max(1, _int(source.get("page"), 1)),
        size=size,
        filters=parse_filters(view.filters if filters is None else filters, source),
    )


def apply_search(stmt: Select[Any], view: ModelView[Any], q: str) -> Select[Any]:
    """Filter `stmt` with a case-insensitive substring match over `view.searchable`."""
    if not q or not view.searchable:
        return stmt
    pattern = f"%{escape_like(q)}%"
    return stmt.where(
        or_(
            *(
                getattr(view.model, name).cast(String).ilike(pattern, escape="\\")
                for name in view.searchable
            )
        )
    )


async def count_rows(session: AsyncSession, stmt: Select[Any]) -> int:
    """Row count of `stmt`, ignoring its ORDER BY."""
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return total or 0


async def count_many(session: AsyncSession, stmts: Sequence[Select[Any]]) -> list[int]:
    """Row counts of several statements in one round trip, in order, ignoring ORDER BY."""
    if not stmts:
        return []
    columns = [
        select(func.count()).select_from(s.order_by(None).subquery()).scalar_subquery()
        for s in stmts
    ]
    row = (await session.execute(select(*columns))).one()
    return [value or 0 for value in row]


def list_statement(view: ModelView[Any], stmt: Select[Any], params: ListParams) -> Select[Any]:
    """`stmt` narrowed by the list's search and filters and ordered by its sort."""
    stmt = apply_search(stmt, view, params.q)
    stmt = apply_filters(stmt, view.model, view.filters, params.filters)
    if params.sort is not None:
        column = getattr(view.model, params.sort)
        order = column.desc() if params.dir == "desc" else column.asc()
        pk_columns = (getattr(view.model, name) for name in view.pk_names)
        stmt = stmt.order_by(None).order_by(order, *pk_columns)
    return stmt


def with_relations(
    stmt: Select[Any], model: type[Any], fields: Sequence[Field | RelationField]
) -> Select[Any]:
    """`stmt` eager-loading every relation among `fields`."""
    return stmt.options(
        *(selectinload(getattr(model, f.name)) for f in fields if isinstance(f, RelationField))
    )


async def run_list(
    session: AsyncSession, view: ModelView[Any], stmt: Select[Any], params: ListParams
) -> ListResult:
    stmt = list_statement(view, stmt, params)
    total = await count_rows(session, stmt)
    pages = max(1, ceil(total / params.size))
    if params.page > pages:
        params = replace(params, page=pages)
    stmt = with_relations(stmt, view.model, view.list_fields)
    stmt = stmt.offset((params.page - 1) * params.size).limit(params.size)
    rows = (await session.scalars(stmt)).all()
    return ListResult(rows=rows, total=total, params=params)


async def fetch_one(
    session: AsyncSession,
    view: ModelView[Any],
    stmt: Select[Any],
    pk: str,
    *,
    relations: Sequence[str] = (),
) -> Any | None:
    """Load one row by pk string, eager-loading exactly the named relations."""
    try:
        clauses = view.pk_clauses(pk)
    except ValueError:
        return None
    stmt = stmt.where(*clauses).options(
        *(selectinload(getattr(view.model, name)) for name in relations)
    )
    return await session.scalar(stmt)
