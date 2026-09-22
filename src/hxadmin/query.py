from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import ceil
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import Select, String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from hxadmin.fields import RelationField
from hxadmin.views import ModelView, SortDir


@dataclass(frozen=True, slots=True)
class ListParams:
    q: str
    sort: str | None
    dir: SortDir
    page: int
    size: int

    def qs(self, **changes: Any) -> str:
        merged = replace(self, **changes)
        pairs = [
            ("q", merged.q or None),
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
    request: Request, view: ModelView[Any], *, query: Mapping[str, str] | None = None
) -> ListParams:
    """List params from `query` (default: the request's query string); invalid values fall back."""
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
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_search(stmt: Select[Any], view: ModelView[Any], q: str) -> Select[Any]:
    """Filter `stmt` with a case-insensitive substring match over `view.searchable`."""
    if not q or not view.searchable:
        return stmt
    pattern = f"%{_escape_like(q)}%"
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


async def run_list(
    session: AsyncSession, view: ModelView[Any], stmt: Select[Any], params: ListParams
) -> ListResult:
    stmt = apply_search(stmt, view, params.q)
    total = await count_rows(session, stmt)
    pages = max(1, ceil(total / params.size))
    if params.page > pages:
        params = replace(params, page=pages)
    if params.sort is not None:
        column = getattr(view.model, params.sort)
        order = column.desc() if params.dir == "desc" else column.asc()
        pk_columns = (getattr(view.model, name) for name in view.pk_names)
        stmt = stmt.order_by(None).order_by(order, *pk_columns)
    stmt = stmt.options(
        *(
            selectinload(getattr(view.model, f.name))
            for f in view.list_fields
            if isinstance(f, RelationField)
        )
    )
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
