from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any, ClassVar, Literal

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from hxadmin.actions import ACTION_ATTR, Action
from hxadmin.export import ExportFormat, check_export_formats
from hxadmin.fields import Field, RelationField, derive_fields
from hxadmin.filters import Filter, resolve_filters
from hxadmin.forms import build_schema
from hxadmin.pk import pk_clauses_for, pk_string_for

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
    list_filters: ClassVar[tuple[str, ...]] = ()
    export_formats: ClassVar[tuple[ExportFormat, ...]] = ()
    export_columns: ClassVar[tuple[str, ...]] = ()
    export_max_rows: ClassVar[int | None] = 10_000

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
        self.writable_fields = self._resolve_form_fields()
        pk_names = set(self.pk_names)
        self.edit_fields = tuple(
            f
            for f in self.writable_fields
            if not (
                f.primary_key
                if isinstance(f, Field)
                else f.fk_columns and pk_names.issuperset(f.fk_columns)
            )
        )
        self.create_schema: type[BaseModel] = build_schema(self.model, self.writable_fields)
        self.edit_schema: type[BaseModel] = build_schema(self.model, self.edit_fields)
        self.actions, self._action_attrs = self._collect_actions()
        self.row_actions = tuple(a for a in self.actions.values() if not a.bulk)
        self.bulk_actions = tuple(a for a in self.actions.values() if a.bulk)
        owner = type(self).__name__
        self.filters: tuple[Filter, ...] = resolve_filters(owner, self.fields, self.list_filters)
        check_export_formats(owner, self.export_formats)
        self.export_fields = (
            self._resolve(self.export_columns) if self.export_columns else self.list_fields
        )

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
            default=derived.default,
            required=derived.required if item.required is None else item.required,
        )

    def _collect_actions(self) -> tuple[dict[str, Action], dict[str, str]]:
        by_attr: dict[str, Action] = {}
        for klass in reversed(type(self).__mro__):
            for attr, value in vars(klass).items():
                spec = getattr(value, ACTION_ATTR, None)
                if isinstance(spec, Action):
                    by_attr[attr] = spec
                else:
                    by_attr.pop(attr, None)
        actions: dict[str, Action] = {}
        attrs: dict[str, str] = {}
        for attr, spec in by_attr.items():
            if spec.name in actions:
                raise ValueError(f"{type(self).__name__}: duplicate action {spec.name!r}")
            actions[spec.name] = spec
            attrs[spec.name] = attr
        return actions, attrs

    def action_handler(self, name: str) -> Callable[..., Awaitable[Any]]:
        """The bound coroutine method declared with `@action(name)`."""
        return getattr(self, self._action_attrs[name])

    def get_query(self, request: Request) -> Select[tuple[T]]:
        return select(self.model)

    def pk_of(self, obj: T) -> str:
        return pk_string_for(self.model, obj)

    def pk_clauses(self, pk: str) -> list[ColumnElement[bool]]:
        return pk_clauses_for(self.model, pk)

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

    def is_action_allowed(self, request: Request, name: str) -> bool:
        """Whether the current user may run action `name`; disallowed actions are hidden, 403."""
        return True

    def permitted_actions(self, request: Request, *, bulk: bool) -> tuple[Action, ...]:
        """Row (or bulk) actions the current user may run, in declaration order."""
        actions = self.bulk_actions if bulk else self.row_actions
        return tuple(a for a in actions if self.is_action_allowed(request, a.name))
