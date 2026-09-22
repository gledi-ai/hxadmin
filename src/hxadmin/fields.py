from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
    inspect,
)
from sqlalchemy.types import TypeEngine

type FieldKind = Literal[
    "str",
    "text",
    "int",
    "float",
    "decimal",
    "bool",
    "date",
    "datetime",
    "time",
    "enum",
    "json",
    "uuid",
]


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: FieldKind
    label: str
    nullable: bool = False
    primary_key: bool = False


@dataclass(frozen=True, slots=True)
class RelationField:
    name: str
    label: str
    target: type[Any]
    multiple: bool
    kind: Literal["relation"] = "relation"


_KINDS: tuple[tuple[type[TypeEngine[Any]], FieldKind], ...] = (
    (Enum, "enum"),
    (Text, "text"),
    (String, "str"),
    (Boolean, "bool"),
    (Integer, "int"),
    (Float, "float"),
    (Numeric, "decimal"),
    (DateTime, "datetime"),
    (Date, "date"),
    (Time, "time"),
    (JSON, "json"),
    (Uuid, "uuid"),
)


def kind_for(type_: TypeEngine[Any]) -> FieldKind:
    for cls, kind in _KINDS:
        if isinstance(type_, cls):
            return kind
    return "str"


def label_for(name: str) -> str:
    return name.replace("_", " ").capitalize()


def derive_fields(model: type[Any]) -> dict[str, Field | RelationField]:
    mapper = inspect(model)
    fields: dict[str, Field | RelationField] = {}
    for key, column in mapper.columns.items():
        fields[key] = Field(
            key,
            kind_for(column.type),
            label_for(key),
            nullable=bool(column.nullable),
            primary_key=bool(column.primary_key),
        )
    for rel in mapper.relationships:
        fields[rel.key] = RelationField(
            rel.key, label_for(rel.key), rel.mapper.class_, multiple=bool(rel.uselist)
        )
    return fields
