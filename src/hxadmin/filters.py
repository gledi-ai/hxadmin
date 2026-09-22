import datetime
import decimal
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Enum,
    Select,
    String,
    Time,
    and_,
    inspect,
    or_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeEngine
from starlette.datastructures import QueryParams
from starlette.requests import Request

from hxadmin.fields import Field, FieldKind, RelationField
from hxadmin.pk import (
    fetch_by_pks,
    in_int64_range,
    pk_clauses_for,
    pk_string_for,
    wide_literal,
)

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin

type FilterKind = Literal["choice", "range", "text", "relation"]

PREFIX = "f."
RELATION_OPTIONS_LIMIT = 100
_TEXT_MAX = 200
_BOOL_CHOICES = (("true", "Yes"), ("false", "No"))
_RANGE_INPUTS: dict[FieldKind, str] = {
    "int": "number",
    "float": "number",
    "decimal": "number",
    "date": "date",
    "datetime": "datetime-local",
    "time": "time",
}
_TEXT_KINDS: frozenset[FieldKind] = frozenset({"str", "text", "uuid"})
_NUMERIC_MAX_ADJUSTED = 131071
_NUMERIC_MIN_EXPONENT = -16383


def filter_key(name: str) -> str:
    """The query param of filter `name`; `.min`, `.max` and `.empty` extend it."""
    return f"{PREFIX}{name}"


@dataclass(frozen=True, slots=True)
class Filter:
    """One declared list filter, resolved from a column or many-to-one relation."""

    name: str
    label: str
    kind: FilterKind
    field: Field | RelationField
    nullable: bool
    choices: tuple[tuple[str, str], ...] = ()
    input_type: str = "text"
    column_type: TypeEngine[Any] | None = None

    @property
    def key(self) -> str:
        return filter_key(self.name)


@dataclass(frozen=True, slots=True)
class FilterValue:
    """The validated query values of one active filter; range bounds in canonical form."""

    name: str
    values: tuple[str, ...] = ()
    min: str | None = None
    max: str | None = None
    empty: bool = False

    def pairs(self) -> list[tuple[str, str]]:
        key = filter_key(self.name)
        pairs = [(key, value) for value in self.values]
        if self.min is not None:
            pairs.append((f"{key}.min", self.min))
        if self.max is not None:
            pairs.append((f"{key}.max", self.max))
        if self.empty:
            pairs.append((f"{key}.empty", "1"))
        return pairs


@dataclass(frozen=True, slots=True)
class Chip:
    """An active filter value shown above the list; removing it clears input `input`."""

    label: str
    input: str
    value: str | None


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _resolve_one(owner: str, model: type[Any], field: Field | RelationField) -> Filter:
    if isinstance(field, RelationField):
        if field.multiple:
            raise ValueError(f"{owner}: cannot filter on to-many relation {field.name!r}")
        if not field.fk_columns:
            raise ValueError(f"{owner}: cannot filter on non-many-to-one relation {field.name!r}")
        return Filter(field.name, field.label, "relation", field, not field.required)
    if field.kind in ("enum", "bool"):
        choices = field.choices if field.kind == "enum" else _BOOL_CHOICES
        return Filter(field.name, field.label, "choice", field, field.nullable, choices)
    if field.kind in _RANGE_INPUTS:
        input_type = _RANGE_INPUTS[field.kind]
        type_ = cast(Mapper[Any], inspect(model)).columns[field.name].type
        return Filter(
            field.name, field.label, "range", field, field.nullable, (), input_type, type_
        )
    if field.kind in _TEXT_KINDS:
        return Filter(field.name, field.label, "text", field, field.nullable)
    raise ValueError(f"{owner}: cannot filter on {field.kind} column {field.name!r}")


def resolve_filters(
    owner: str,
    model: type[Any],
    fields: Mapping[str, Field | RelationField],
    names: Sequence[str],
) -> tuple[Filter, ...]:
    """Resolve `list_filters` names; ValueError for unknown or unfilterable fields."""
    resolved: list[Filter] = []
    for name in names:
        field = fields.get(name)
        if field is None:
            raise ValueError(f"{owner}: unknown field {name!r}")
        resolved.append(_resolve_one(owner, model, field))
    return tuple(resolved)


def _naive_column(filter_: Filter) -> bool:
    type_ = filter_.column_type
    return isinstance(type_, DateTime | Time) and not type_.timezone


def _range_value(filter_: Filter, raw: str) -> Any:
    """The bound `raw` parsed for the filter's column; ValueError if no database accepts it.

    An aware datetime on a naive column becomes naive UTC; an aware time there is rejected.
    """
    kind = filter_.field.kind
    try:
        if kind == "int":
            number = int(raw)
            if not in_int64_range(number):
                raise ValueError(raw)
            return number
        if kind == "float":
            number = float(raw)
            if not math.isfinite(number):
                raise ValueError(raw)
            return number
        if kind == "decimal":
            amount = decimal.Decimal(raw)
            exponent = amount.as_tuple().exponent
            if (
                not isinstance(exponent, int)
                or exponent < _NUMERIC_MIN_EXPONENT
                or amount.adjusted() > _NUMERIC_MAX_ADJUSTED
            ):
                raise ValueError(raw)
            return amount
        if kind == "date":
            return datetime.date.fromisoformat(raw)
        if kind == "datetime":
            moment = datetime.datetime.fromisoformat(raw)
            if moment.tzinfo is not None and _naive_column(filter_):
                return moment.astimezone(datetime.UTC).replace(tzinfo=None)
            return moment
        clock = datetime.time.fromisoformat(raw)
        if clock.tzinfo is not None and _naive_column(filter_):
            raise ValueError(raw)
        return clock
    except ArithmeticError:
        raise ValueError(raw) from None


def _canonical(value: Any) -> str:
    """`value` written the way the filter's HTML input writes it."""
    if isinstance(value, datetime.datetime | datetime.time):
        whole_minutes = value.second == 0 and value.microsecond == 0
        return value.isoformat(timespec="minutes" if whole_minutes else "auto")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return str(int(value))
    return repr(value) if isinstance(value, float) else str(value)


def _valid_bound(filter_: Filter, raw: str | None) -> str | None:
    if isinstance(filter_.field, RelationField) or raw is None or raw.strip() == "":
        return None
    try:
        return _canonical(_range_value(filter_, raw.strip()))
    except ValueError:
        return None


def _valid_choice(filter_: Filter, raw: str) -> bool:
    if isinstance(filter_.field, RelationField):
        try:
            pk_clauses_for(filter_.field.target, raw)
        except ValueError:
            return False
        return True
    return raw in dict(filter_.choices)


def parse_filters(filters: Sequence[Filter], source: QueryParams) -> tuple[FilterValue, ...]:
    """Active filter values from query params; invalid values are dropped."""
    active: list[FilterValue] = []
    for filter_ in filters:
        key = filter_.key
        values: tuple[str, ...] = ()
        low = high = None
        if filter_.kind == "range":
            low = _valid_bound(filter_, source.get(f"{key}.min"))
            high = _valid_bound(filter_, source.get(f"{key}.max"))
        elif filter_.kind == "text":
            text = (source.get(key) or "").strip()[:_TEXT_MAX]
            values = (text,) if text else ()
        else:
            picked = (v for v in source.getlist(key) if _valid_choice(filter_, v))
            values = tuple(dict.fromkeys(picked))
        empty = filter_.nullable and source.get(f"{key}.empty") == "1"
        if values or low is not None or high is not None or empty:
            active.append(FilterValue(filter_.name, values, low, high, empty))
    return tuple(active)


def _choice_value(model: type[Any], filter_: Filter, raw: str) -> Any:
    if filter_.field.kind == "bool":
        return raw == "true"
    type_ = cast(Mapper[Any], inspect(model)).columns[filter_.name].type
    if isinstance(type_, Enum) and type_.enum_class is not None:
        return next(m for m in type_.enum_class if str(m.value) == raw)
    return raw


def _bound(filter_: Filter, raw: str) -> Any:
    value = _range_value(filter_, raw)
    return value if filter_.column_type is None else wide_literal(filter_.column_type, value)


def _clause(model: type[Any], filter_: Filter, value: FilterValue) -> ColumnElement[bool]:
    field = filter_.field
    conditions: list[ColumnElement[bool]] = []
    if isinstance(field, RelationField):
        relation = getattr(model, field.name)
        if value.values:
            matches = [and_(*pk_clauses_for(field.target, pk)) for pk in value.values]
            conditions.append(relation.has(or_(*matches)))
        missing = and_(*(getattr(model, name).is_(None) for name in field.fk_columns))
    else:
        column = getattr(model, field.name)
        missing = column.is_(None)
        if filter_.kind == "choice" and value.values:
            conditions.append(column.in_([_choice_value(model, filter_, v) for v in value.values]))
        elif filter_.kind == "text" and value.values:
            pattern = f"%{escape_like(value.values[0])}%"
            conditions.append(column.cast(String).ilike(pattern, escape="\\"))
        if value.min is not None:
            conditions.append(column >= _bound(filter_, value.min))
        if value.max is not None:
            conditions.append(column <= _bound(filter_, value.max))
    if not value.empty:
        return and_(*conditions)
    if not conditions:
        return missing
    return or_(and_(*conditions), missing)


def apply_filters(
    stmt: Select[Any],
    model: type[Any],
    filters: Sequence[Filter],
    values: Sequence[FilterValue],
) -> Select[Any]:
    """Narrow `stmt` by every active filter value (AND across filters)."""
    by_name = {f.name: f for f in filters}
    for value in values:
        filter_ = by_name.get(value.name)
        if filter_ is not None:
            stmt = stmt.where(_clause(model, filter_, value))
    return stmt


def visible_filters(
    admin: "HxAdmin", request: Request, filters: Sequence[Filter]
) -> tuple[Filter, ...]:
    """Filters the current user may use: relation filters need an accessible target."""
    return tuple(
        f
        for f in filters
        if not isinstance(f.field, RelationField) or admin.can_reach(request, f.field.target)
    )


async def relation_labels(
    admin: "HxAdmin",
    request: Request,
    session: AsyncSession,
    filters: Sequence[Filter],
    values: Sequence[FilterValue],
    *,
    with_options: bool,
) -> dict[str, list[tuple[str, str]]]:
    """`(pk, label)` pairs per relation filter: the selected rows, plus the first options."""
    selected = {v.name: v.values for v in values}
    labels: dict[str, list[tuple[str, str]]] = {}
    for filter_ in filters:
        field = filter_.field
        chosen = selected.get(filter_.name, ())
        if not isinstance(field, RelationField) or not (with_options or chosen):
            continue
        stmt = admin.relation_scope(request, field.target)
        if stmt is None:
            continue
        rows: list[Any] = []
        if with_options:
            pk_columns = cast(Mapper[Any], inspect(field.target)).primary_key
            limited = stmt.order_by(*pk_columns).limit(RELATION_OPTIONS_LIMIT)
            rows.extend((await session.scalars(limited)).all())
        if chosen:
            rows.extend(await fetch_by_pks(session, field.target, list(chosen), stmt=stmt))
        pairs = {pk_string_for(field.target, row): admin.display(row) for row in rows}
        labels[filter_.name] = list(pairs.items())
    return labels


def filter_chips(
    filters: Sequence[Filter],
    values: Sequence[FilterValue],
    labels: Mapping[str, Sequence[tuple[str, str]]],
) -> list[Chip]:
    """One removable chip per active filter value."""
    by_name = {f.name: f for f in filters}
    chips: list[Chip] = []
    for value in values:
        filter_ = by_name.get(value.name)
        if filter_ is None:
            continue
        names = dict(filter_.choices) | dict(labels.get(filter_.name, ()))
        for raw in value.values:
            if filter_.kind == "text":
                chips.append(Chip(f"{filter_.label} contains “{raw}”", filter_.key, None))
            else:
                chips.append(Chip(f"{filter_.label}: {names.get(raw, raw)}", filter_.key, raw))
        if value.min is not None:
            chips.append(Chip(f"{filter_.label} ≥ {value.min}", f"{filter_.key}.min", None))
        if value.max is not None:
            chips.append(Chip(f"{filter_.label} ≤ {value.max}", f"{filter_.key}.max", None))
        if value.empty:
            chips.append(Chip(f"{filter_.label}: empty", f"{filter_.key}.empty", "1"))
    return chips
