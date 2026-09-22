from collections.abc import Sequence
from dataclasses import replace
from typing import Any, ClassVar, Literal, cast

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeEngine
from starlette.requests import Request

from hxadmin.fields import Field, RelationField, derive_fields
from hxadmin.forms import build_schema

type SortDir = Literal["asc", "desc"]


class ModelView[T]:
    """Configuration for one SQLAlchemy model in the admin."""

    model: type[T]
    name: ClassVar[str]
    name_plural: ClassVar[str]
    identity: ClassVar[str]
    category: ClassVar[str | None] = None
    icon: ClassVar[str | None] = None

    list_columns: ClassVar[tuple[str, ...]] = ()
    detail_columns: ClassVar[tuple[str, ...]] = ()
    searchable: ClassVar[tuple[str, ...]] = ()
    sortable: ClassVar[tuple[str, ...]] = ()
    default_sort: ClassVar[tuple[str, SortDir] | None] = None
    page_size: ClassVar[int] = 25
    page_size_options: ClassVar[tuple[int, ...]] = (25, 50, 100)
    can_view: ClassVar[bool] = True
    form_fields: ClassVar[tuple[str | Field, ...]] = ()
    form_exclude: ClassVar[tuple[str, ...]] = ()
    can_create: ClassVar[bool] = True
    can_edit: ClassVar[bool] = True
    can_delete: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "model" not in cls.__dict__ and not hasattr(cls, "model"):
            raise TypeError(f"{cls.__name__} must define `model`")
        if "model" in cls.__dict__:
            model_name: str = cls.model.__name__
            cls.name = cls.__dict__.get("name", model_name)
            cls.name_plural = cls.__dict__.get("name_plural", f"{cls.name}s")
            cls.identity = cls.__dict__.get("identity", model_name.lower())
        else:
            cls.name = cls.__dict__.get("name", cls.name)
            cls.name_plural = cls.__dict__.get("name_plural", cls.name_plural)
            cls.identity = cls.__dict__.get("identity", cls.identity)

    def __init__(self) -> None:
        self.fields = derive_fields(self.model)
        column_fields = [f for f in self.fields.values() if isinstance(f, Field)]
        self.pk_names = tuple(f.name for f in column_fields if f.primary_key)
        self.list_fields = self._resolve(self.list_columns or tuple(f.name for f in column_fields))
        self.detail_fields = self._resolve(self.detail_columns or tuple(self.fields))
        self.sort_names = self.sortable or tuple(
            f.name for f in self.list_fields if isinstance(f, Field)
        )
        for name in (*self.searchable, *self.sort_names):
            if not isinstance(self.fields.get(name), Field):
                raise ValueError(f"{type(self).__name__}: {name!r} is not a column")
        if self.default_sort is not None and self.default_sort[0] not in self.sort_names:
            raise ValueError(f"{type(self).__name__}: {self.default_sort[0]!r} is not sortable")
        self.formatted = frozenset(
            name for name in self.fields if callable(getattr(self, f"format_{name}", None))
        )
        mapper = cast(Mapper[T], inspect(self.model))
        self._pk_types: dict[str, TypeEngine[Any]] = {
            name: mapper.columns[name].type for name in self.pk_names
        }
        self.writable_fields = self._resolve_form_fields()
        self.edit_fields = tuple(
            f for f in self.writable_fields if not (isinstance(f, Field) and f.primary_key)
        )
        self.create_schema: type[BaseModel] = build_schema(self.model, self.writable_fields)
        self.edit_schema: type[BaseModel] = build_schema(self.model, self.edit_fields)

    def _resolve(self, names: Sequence[str]) -> tuple[Field | RelationField, ...]:
        try:
            return tuple(self.fields[name] for name in names)
        except KeyError as exc:
            raise ValueError(f"{type(self).__name__}: unknown field {exc.args[0]!r}") from None

    def _resolve_form_fields(self) -> tuple[Field | RelationField, ...]:
        if self.form_fields:
            resolved = [self._resolve_form_field(item) for item in self.form_fields]
        else:
            fk_columns = {
                name
                for f in self.fields.values()
                if isinstance(f, RelationField)
                for name in f.fk_columns
            }
            columns = [
                f
                for f in self.fields.values()
                if isinstance(f, Field)
                and not (f.primary_key and f.autoincrement)
                and f.name not in fk_columns
            ]
            relations = [f for f in self.fields.values() if isinstance(f, RelationField)]
            resolved = [*columns, *relations]
        return tuple(f for f in resolved if f.name not in self.form_exclude)

    def _resolve_form_field(self, item: str | Field) -> Field | RelationField:
        if isinstance(item, str):
            return self._resolve((item,))[0]
        derived = self.fields.get(item.name)
        if not isinstance(derived, Field):
            raise ValueError(f"{type(self).__name__}: {item.name!r} is not a column")
        return replace(
            item,
            kind=derived.kind,
            nullable=derived.nullable,
            primary_key=derived.primary_key,
            autoincrement=derived.autoincrement,
            unique=derived.unique,
            choices=derived.choices,
        )

    def get_query(self, request: Request) -> Select[tuple[T]]:
        return select(self.model)

    def pk_of(self, obj: T) -> str:
        return ";".join(str(getattr(obj, name)) for name in self.pk_names)

    def pk_clauses(self, pk: str) -> list[ColumnElement[bool]]:
        raw = pk.split(";")
        if len(raw) != len(self.pk_names):
            raise ValueError(pk)
        clauses: list[ColumnElement[bool]] = []
        for name, value in zip(self.pk_names, raw, strict=True):
            clauses.append(getattr(self.model, name) == _coerce(self._pk_types[name], value))
        return clauses

    def display(self, obj: T) -> str:
        if type(obj).__str__ is not object.__str__:
            return str(obj)
        return f"{self.name} {self.pk_of(obj)}"

    def cell(self, obj: T, name: str) -> Any:
        if name in self.formatted:
            return getattr(self, f"format_{name}")(obj)
        return getattr(obj, name)

    async def on_save(
        self, request: Request, session: AsyncSession, obj: T, *, created: bool
    ) -> None:
        return None

    async def on_delete(self, request: Request, session: AsyncSession, obj: T) -> None:
        return None

    def is_visible(self, request: Request) -> bool:
        return True

    def is_accessible(self, request: Request) -> bool:
        return True


def _coerce(type_: TypeEngine[Any], value: str) -> Any:
    try:
        python_type = type_.python_type
    except NotImplementedError:
        return value
    try:
        return python_type(value)
    except TypeError:
        return value
