import enum
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
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
from sqlalchemy.orm import Mapper, RelationshipDirection
from sqlalchemy.sql.schema import ScalarElementColumnDefault
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

type Widget = Literal[
    "text",
    "textarea",
    "number",
    "checkbox",
    "date",
    "datetime-local",
    "time",
    "select",
    "email",
    "url",
    "password",
    "json",
]


@dataclass(frozen=True, slots=True)
class Field:
    """A form/list column.

    `required` is tri-state: `True`/`False` force it, `None` (the default for `Field(...)`
    overrides in `form_fields`) means "derive from the column": on a `ModelView` that is the
    mapper-derived value, elsewhere it means non-nullable. `kind`, `nullable`, `autoincrement`,
    `unique`, `choices` and `default` always describe the column, and `primary_key` the
    mapper's key (so a `__mapper_args__` primary key counts); all are replaced by the derived
    values when used as an override.
    """

    name: str
    kind: FieldKind
    label: str = ""
    nullable: bool = False
    primary_key: bool = False
    autoincrement: bool = False
    unique: bool = False
    required: bool | None = None
    default: Any = None
    choices: tuple[tuple[str, str], ...] = ()
    widget: Widget | None = None
    help_text: str | None = None
    readonly: bool = False

    def __post_init__(self) -> None:
        if self.label == "":
            object.__setattr__(self, "label", label_for(self.name))


@dataclass(frozen=True, slots=True)
class RelationField:
    name: str
    label: str
    target: type[Any]
    multiple: bool
    fk_columns: tuple[str, ...] = ()
    kind: Literal["relation"] = "relation"
    required: bool = False
    help_text: str | None = None


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

_WIDGETS: dict[FieldKind, Widget] = {
    "str": "text",
    "text": "textarea",
    "int": "number",
    "float": "number",
    "decimal": "number",
    "bool": "checkbox",
    "date": "date",
    "datetime": "datetime-local",
    "time": "time",
    "enum": "select",
    "json": "json",
    "uuid": "text",
}


def kind_for(type_: TypeEngine[Any]) -> FieldKind:
    for cls, kind in _KINDS:
        if isinstance(type_, cls):
            return kind
    return "str"


def default_widget(kind: FieldKind) -> Widget:
    return _WIDGETS[kind]


_HALF_WIDGETS: frozenset[str] = frozenset(
    {"select", "number", "checkbox", "date", "datetime-local", "time"}
)


def field_widget(field: Field | RelationField) -> Widget | Literal["relation"]:
    """The widget a form renders for `field`: its override, else the default for its kind."""
    if isinstance(field, RelationField):
        return "relation"
    return field.widget or default_widget(field.kind)


def field_width(field: Field | RelationField) -> Literal["half", "full"]:
    """`"half"` for short controls (selects, numbers, dates, single relations), else `"full"`."""
    if isinstance(field, RelationField):
        return "full" if field.multiple else "half"
    return "half" if field_widget(field) in _HALF_WIDGETS else "full"


def label_for(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _choices_for(type_: TypeEngine[Any]) -> tuple[tuple[str, str], ...]:
    if not isinstance(type_, Enum):
        return ()
    if type_.enum_class is not None:
        return tuple((str(m.value), str(m.value)) for m in type_.enum_class)
    return tuple((v, v) for v in type_.enums)


def _default_for(column: Column[Any]) -> Any:
    default = column.default
    if not isinstance(default, ScalarElementColumnDefault):
        return None
    value = default.arg
    if isinstance(value, enum.Enum):
        return str(value.value)
    return value


def _is_autoincrement(column: Column[Any], mapper: Mapper[Any]) -> bool:
    return (
        bool(column.primary_key)
        and column.autoincrement in ("auto", True)
        and isinstance(column.type, Integer)
        and len(mapper.primary_key) == 1
    )


def _column_field(key: str, column: Column[Any], mapper: Mapper[Any]) -> Field:
    kind = kind_for(column.type)
    nullable = bool(column.nullable)
    autoincrement = _is_autoincrement(column, mapper)
    required = (
        not nullable
        and column.default is None
        and column.server_default is None
        and not autoincrement
        and kind != "bool"
    )
    return Field(
        key,
        kind,
        nullable=nullable,
        primary_key=any(c is column for c in mapper.primary_key),
        autoincrement=autoincrement,
        unique=bool(column.unique),
        required=required,
        default=_default_for(column),
        choices=_choices_for(column.type),
    )


def derive_fields(model: type[Any]) -> dict[str, Field | RelationField]:
    mapper = inspect(model)
    fields: dict[str, Field | RelationField] = {}
    for key, column in mapper.columns.items():
        fields[key] = _column_field(key, column, mapper)
    for rel in mapper.relationships:
        many_to_one = rel.direction is RelationshipDirection.MANYTOONE
        local_columns = tuple(rel.local_columns) if many_to_one else ()
        fields[rel.key] = RelationField(
            rel.key,
            label_for(rel.key),
            rel.mapper.class_,
            multiple=bool(rel.uselist),
            fk_columns=tuple(mapper.get_property_by_column(c).key for c in local_columns),
            required=many_to_one and all(not c.nullable for c in local_columns),
        )
    return fields
