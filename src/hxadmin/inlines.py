from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import RelationshipProperty, with_parent
from starlette import status
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException
from starlette.requests import Request

from hxadmin.fields import Field, RelationField
from hxadmin.forms import FormErrors, build_schema, initial_values, parse_form, validate
from hxadmin.query import with_relations

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin
    from hxadmin.views import ModelView

_INLINE_LIMIT = 20
_ROW_MARKER = re.compile(r"_hx_inline\.[0-9]+\.[0-9a-f]{32}")


def related_form_fields(
    fields: Sequence[Field | RelationField], relationship: RelationshipProperty[Any]
) -> tuple[Field | RelationField, ...]:
    bound_keys = {
        relationship.mapper.get_property_by_column(child).key
        for _, child in relationship.synchronize_pairs
    }
    return tuple(
        f
        for f in fields
        if f.name not in bound_keys
        and f.name != relationship.back_populates
        and not (isinstance(f, RelationField) and bound_keys.intersection(f.fk_columns))
    )


@dataclass(slots=True)
class InlineRow:
    marker: str
    fields: tuple[Field | RelationField, ...]
    values: dict[str, Any]
    obj: Any = None
    pk: str | None = None
    label: str | None = None
    active: bool = False
    errors: FormErrors = field(default_factory=FormErrors)


@dataclass(slots=True)
class InlineGroup:
    index: int
    name: str
    label: str
    view: ModelView[Any]
    relationship: RelationshipProperty[Any]
    can_create: bool
    can_edit: bool
    rows: list[InlineRow] = field(default_factory=list)
    truncated: bool = False

    @property
    def prefix(self) -> str:
        return f"_hx_inline.{self.index}"

    def new_row(self, admin: HxAdmin, marker: str | None = None) -> InlineRow:
        fields = related_form_fields(self.view.writable_fields, self.relationship)
        return InlineRow(
            marker or f"{self.prefix}.{uuid4().hex}",
            fields,
            initial_values(admin, self.view, None, fields),
            active=True,
        )


@dataclass(slots=True)
class InlineChange:
    group: InlineGroup
    row: InlineRow
    raw: dict[str, Any]
    values: dict[str, Any]


def inline_group(
    admin: HxAdmin, request: Request, view: ModelView[Any], name: str
) -> InlineGroup | None:
    if name not in view.form_inlines:
        return None
    relationship = inspect(view.model, raiseerr=True).relationships[name]
    target = admin.view_for(relationship.mapper.class_)
    if target is None or not target.is_accessible(request):
        return None
    can_create = target.allows_operation(request, "create")
    can_edit = target.allows_operation(request, "edit")
    if not (can_create or can_edit):
        return None
    return InlineGroup(
        view.form_inlines.index(name),
        name,
        view.fields[name].label,
        target,
        relationship,
        can_create,
        can_edit,
    )


async def load_inlines(
    admin: HxAdmin,
    request: Request,
    session: AsyncSession,
    view: ModelView[Any],
    parent: Any,
) -> list[InlineGroup]:
    groups = inline_groups(admin, request, view)
    for group in groups:
        if not group.can_edit:
            continue
        target = group.view
        fields = related_form_fields(target.edit_fields, group.relationship)
        relation_filter = with_parent(parent, group.relationship.class_attribute)
        stmt = target.get_query(request).where(relation_filter)
        stmt = with_relations(stmt, target.model, target.edit_fields)
        pk_columns = group.relationship.mapper.primary_key
        rows = (
            (await session.scalars(stmt.order_by(*pk_columns).limit(_INLINE_LIMIT + 1)))
            .unique()
            .all()
        )
        group.truncated = len(rows) > _INLINE_LIMIT
        for obj in rows[:_INLINE_LIMIT]:
            group.rows.append(
                InlineRow(
                    f"{group.prefix}.{uuid4().hex}",
                    fields,
                    initial_values(admin, target, obj, fields),
                    obj=obj,
                    pk=target.pk_of(obj),
                    label=target.display(obj),
                )
            )
    return groups


def inline_groups(
    admin: HxAdmin, request: Request, view: ModelView[Any], *, created: bool = False
) -> list[InlineGroup]:
    groups = []
    for name in view.form_inlines:
        group = inline_group(admin, request, view, name)
        if group is not None and (not created or group.can_create):
            groups.append(group)
    return groups


def parse_inlines(
    admin: HxAdmin, groups: Sequence[InlineGroup], form: FormData
) -> list[InlineChange]:
    by_prefix = {group.prefix: group for group in groups}
    existing = {group.prefix: {row.pk: row for row in group.rows} for group in groups}
    seen: set[tuple[type[Any], str]] = set()
    schemas = {}
    changes = []
    for marker, key in form.multi_items():
        if not _ROW_MARKER.fullmatch(marker):
            continue
        prefix, _ = marker.rsplit(".", 1)
        group = by_prefix.get(prefix)
        if group is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN)
        if len(form.getlist(marker)) != 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Submit each related row only once."
            )
        if key == "new" and group.can_create:
            row = group.new_row(admin, marker)
            group.rows.append(row)
        elif isinstance(key, str) and key.startswith("edit:") and group.can_edit:
            pk = key.removeprefix("edit:")
            row = existing[prefix].get(pk)
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            identity = (group.view.model, pk)
            if identity in seen:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Submit each related record only once."
                )
            seen.add(identity)
            row.marker = marker
            row.active = True
        else:
            raise HTTPException(status.HTTP_403_FORBIDDEN)
        created = row.pk is None
        raw = parse_form(row.fields, form, created=created, prefix=f"{marker}.")
        schema_key = (prefix, created)
        if schema_key not in schemas:
            schemas[schema_key] = build_schema(group.view.model, row.fields)
        values, row.errors = validate(schemas[schema_key], raw)
        changes.append(InlineChange(group, row, raw, values))
    return changes
