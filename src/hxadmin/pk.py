from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Float,
    Integer,
    Numeric,
    Select,
    and_,
    inspect,
    literal,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeEngine


def _pk_keys(mapper: Mapper[Any]) -> list[tuple[str, ColumnElement[Any]]]:
    return [(mapper.get_property_by_column(c).key, c) for c in mapper.primary_key]


def pk_string_for(model: type[Any], obj: Any) -> str:
    """Join the primary key values of `obj` with `;` in mapper primary-key order."""
    mapper = cast(Mapper[Any], inspect(model))
    return ";".join(str(getattr(obj, key)) for key, _ in _pk_keys(mapper))


def pk_clauses_for(model: type[Any], pk: str) -> list[ColumnElement[bool]]:
    """Turn a `;`-joined pk string into equality clauses; ValueError if it does not fit."""
    mapper = cast(Mapper[Any], inspect(model))
    keys = _pk_keys(mapper)
    raw = pk.split(";")
    if len(raw) != len(keys):
        raise ValueError(pk)
    return [
        getattr(model, key) == wide_literal(column.type, _coerce(column.type, value))
        for (key, column), value in zip(keys, raw, strict=True)
    ]


INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def in_int64_range(value: int) -> bool:
    """SQLite and asyncpg only accept signed 64-bit integers; anything else raises at execution."""
    return INT64_MIN <= value <= INT64_MAX


def wide_literal(type_: TypeEngine[Any], value: Any) -> Any:
    """`value` bound as BIGINT, FLOAT or unconstrained NUMERIC for a column of that family.

    asyncpg casts each bind to the column's type, so a value wider than an INTEGER or
    NUMERIC(p, s) column would raise instead of simply not matching.
    """
    if isinstance(type_, Integer):
        return literal(value, BigInteger())
    if isinstance(type_, Float):
        return literal(value, Float())
    if isinstance(type_, Numeric):
        return literal(value, Numeric(asdecimal=type_.asdecimal))
    return value


def _coerce(type_: TypeEngine[Any], value: str) -> Any:
    try:
        python_type = type_.python_type
    except NotImplementedError:
        return value
    try:
        converted = python_type(value)
    except (TypeError, ValueError):
        raise ValueError(value) from None
    if python_type is int and not in_int64_range(converted):
        raise ValueError(value)
    return converted


async def fetch_by_pks(
    session: AsyncSession,
    model: type[Any],
    pks: Sequence[str],
    *,
    stmt: Select[Any] | None = None,
) -> list[Any]:
    """Load rows for the given pk strings in one query, ordered as `pks`; unknown pks are absent."""
    clauses = []
    for pk in pks:
        try:
            clauses.append(and_(*pk_clauses_for(model, pk)))
        except ValueError:
            continue
    if not clauses:
        return []
    base = select(model) if stmt is None else stmt
    rows = (await session.scalars(base.where(or_(*clauses)))).all()
    by_pk = {pk_string_for(model, row): row for row in rows}
    return [by_pk[pk] for pk in pks if pk in by_pk]
