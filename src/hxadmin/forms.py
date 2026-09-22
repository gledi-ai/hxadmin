import dataclasses
import datetime
import decimal
import enum
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Json, ValidationError, create_model
from pydantic import Field as PydField
from sqlalchemy import Enum, Select, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeEngine
from starlette.datastructures import FormData
from starlette.requests import Request

from hxadmin.fields import Field, FieldKind, RelationField
from hxadmin.pk import fetch_by_pks, pk_string_for

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin
    from hxadmin.views import ModelView

_TYPES: dict[FieldKind, Any] = {
    "str": str,
    "text": str,
    "uuid": uuid.UUID,
    "int": int,
    "float": float,
    "decimal": decimal.Decimal,
    "bool": bool,
    "date": datetime.date,
    "datetime": datetime.datetime,
    "time": datetime.time,
    "json": Json[Any],
}

_STRING_KINDS: frozenset[FieldKind] = frozenset({"str", "text"})


def _annotation(field: Field) -> Any:
    if field.kind == "enum":
        return cast(Any, Literal)[tuple(value for value, _ in field.choices)]
    return _TYPES[field.kind]


def is_required(field: Field) -> bool:
    """A `Field` with `required=None` is required exactly when its column is non-nullable."""
    return not field.nullable if field.required is None else field.required


def _column_definition(field: Field) -> tuple[Any, Any]:
    if field.kind == "bool":
        return bool, False
    annotation = _annotation(field)
    if not is_required(field):
        return annotation | None, None
    if field.kind in _STRING_KINDS:
        return annotation, PydField(min_length=1)
    return annotation, ...


def _relation_definition(field: RelationField) -> tuple[Any, Any]:
    if field.multiple:
        return list[str], PydField(default_factory=list)
    if field.required:
        return str, PydField(min_length=1)
    return str | None, None


def build_schema(model: type[Any], fields: Sequence[Field | RelationField]) -> type[BaseModel]:
    """Build a pydantic model validating raw form values for the given fields."""
    definitions: dict[str, Any] = {}
    for field in fields:
        if isinstance(field, RelationField):
            definitions[field.name] = _relation_definition(field)
        elif not field.readonly:
            definitions[field.name] = _column_definition(field)
    return create_model(
        f"{model.__name__}Form",
        __config__=ConfigDict(extra="ignore", str_strip_whitespace=True),
        **definitions,
    )


@dataclasses.dataclass(frozen=True, slots=True)
class FormErrors:
    fields: dict[str, str] = dataclasses.field(default_factory=dict)
    form: str | None = None

    def __bool__(self) -> bool:
        return bool(self.fields or self.form)


_REQUIRED_TYPES = frozenset({"missing", "string_too_short"})
_REQUIRED_MESSAGE = "This field is required."


def _single(form: FormData, name: str) -> str | None:
    value = form.get(name)
    return value if isinstance(value, str) else None


_OMITTED = object()


def _column_raw(field_: Field, form: FormData, *, created: bool) -> Any:
    if field_.kind == "bool":
        return "on" if field_.name in form else False
    value = _single(form, field_.name) or ""
    if value != "":
        return value
    if field_.nullable:
        return None
    if field_.kind in _STRING_KINDS:
        return value
    return _OMITTED if created and not is_required(field_) else value


def parse_form(
    fields: Sequence[Field | RelationField], form: FormData, *, created: bool
) -> dict[str, Any]:
    """Turn submitted form data into raw values keyed by field name.

    An empty non-nullable column is left out on create so the model default applies at
    flush; on edit it stays in as `""` and validation reports it as required.
    """
    raw: dict[str, Any] = {}
    for field_ in fields:
        if isinstance(field_, RelationField):
            if field_.multiple:
                raw[field_.name] = [
                    v for v in form.getlist(field_.name) if isinstance(v, str) and v != ""
                ]
            else:
                raw[field_.name] = _single(form, field_.name) or None
        elif not field_.readonly:
            value = _column_raw(field_, form, created=created)
            if value is not _OMITTED:
                raw[field_.name] = value
    return raw


def _message(error: Mapping[str, Any]) -> str:
    if error["type"] in _REQUIRED_TYPES or error.get("input") in (None, ""):
        return _REQUIRED_MESSAGE
    return str(error["msg"])


def validate(schema: type[BaseModel], raw: Mapping[str, Any]) -> tuple[dict[str, Any], FormErrors]:
    """Validate raw values against `schema`; return (values, errors) with one message per field."""
    try:
        model = schema.model_validate(raw)
    except ValidationError as exc:
        fields: dict[str, str] = {}
        form: str | None = None
        for error in exc.errors():
            loc = error["loc"]
            if loc:
                fields.setdefault(str(loc[0]), _message(error))
            elif form is None:
                form = str(error["msg"])
        return {}, FormErrors(fields, form)
    return model.model_dump(exclude_unset=True), FormErrors()


def _column_value(type_: TypeEngine[Any], value: Any) -> Any:
    if value is None or not isinstance(type_, Enum) or type_.enum_class is None:
        return value
    members: dict[str, enum.Enum] = {str(m.value): m for m in type_.enum_class}
    return members[str(value)]


def relation_scope(admin: "HxAdmin", request: Request, field_: RelationField) -> Select[Any]:
    """Statement a form may resolve `field_`'s pks against; LookupError if the target is locked."""
    target = admin.view_for(field_.target)
    if target is None:
        return select(field_.target)
    if not target.is_accessible(request):
        raise LookupError(field_.name)
    return target.get_query(request)


async def _relation_value(
    session: AsyncSession, stmt: Select[Any], field_: RelationField, value: Any
) -> Any:
    if field_.multiple:
        pks = list(dict.fromkeys(str(v) for v in value))
        rows = await fetch_by_pks(session, field_.target, pks, stmt=stmt)
        if len(rows) != len(pks):
            raise LookupError(field_.name)
        return rows
    if value is None:
        return None
    rows = await fetch_by_pks(session, field_.target, [str(value)], stmt=stmt)
    if not rows:
        raise LookupError(field_.name)
    return rows[0]


async def apply(
    admin: "HxAdmin",
    request: Request,
    session: AsyncSession,
    view: "ModelView[Any]",
    obj: Any,
    values: Mapping[str, Any],
    fields: Sequence[Field | RelationField],
) -> None:
    """Write validated values onto `obj`, resolving relation pk strings through the target view."""
    columns = cast(Mapper[Any], inspect(view.model)).columns
    for field_ in fields:
        if field_.name not in values:
            continue
        value = values[field_.name]
        if isinstance(field_, RelationField):
            stmt = relation_scope(admin, request, field_)
            setattr(obj, field_.name, await _relation_value(session, stmt, field_, value))
        elif not field_.readonly:
            setattr(obj, field_.name, _column_value(columns[field_.name].type, value))


def _relation_initial(admin: "HxAdmin", field_: RelationField, obj: Any) -> list[tuple[str, str]]:
    related = getattr(obj, field_.name)
    items = related if field_.multiple else ([] if related is None else [related])
    return [(pk_string_for(field_.target, item), admin.display(item)) for item in items]


def _column_initial(field_: Field, obj: Any | None) -> Any:
    if obj is None:
        if field_.kind == "bool" and field_.default is None:
            return False
        return field_.default
    value = getattr(obj, field_.name)
    return str(value.value) if isinstance(value, enum.Enum) else value


def initial_values(
    admin: "HxAdmin",
    view: "ModelView[Any]",
    obj: Any | None,
    fields: Sequence[Field | RelationField],
) -> dict[str, Any]:
    """Values to pre-fill a form: column defaults for create, object state for edit."""
    values: dict[str, Any] = {}
    for field_ in fields:
        if isinstance(field_, RelationField):
            values[field_.name] = [] if obj is None else _relation_initial(admin, field_, obj)
        else:
            values[field_.name] = _column_initial(field_, obj)
    return values


def form_relations(fields: Sequence[Field | RelationField]) -> list[str]:
    return [f.name for f in fields if isinstance(f, RelationField)]


async def relabel(
    admin: "HxAdmin",
    request: Request,
    session: AsyncSession,
    fields: Sequence[Field | RelationField],
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-resolve relation pk strings in re-submitted raw values to `(pk, label)` chips."""
    values = dict(raw)
    for field_ in fields:
        if not isinstance(field_, RelationField):
            continue
        value = raw.get(field_.name)
        pks = [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []
        try:
            stmt = relation_scope(admin, request, field_)
        except LookupError:
            values[field_.name] = []
            continue
        rows = await fetch_by_pks(session, field_.target, pks, stmt=stmt)
        values[field_.name] = [(pk_string_for(field_.target, r), admin.display(r)) for r in rows]
    return values
