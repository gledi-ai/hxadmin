import datetime
import decimal
import uuid
from collections.abc import Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Json, create_model
from pydantic import Field as PydField

from hxadmin.fields import Field, FieldKind, RelationField

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


def _column_definition(field: Field) -> tuple[Any, Any]:
    if field.kind == "bool":
        return bool, False
    annotation = _annotation(field)
    if not field.required:
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
