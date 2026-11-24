import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

type AuditOperation = Literal["create", "update", "delete"]
type Snapshot = dict[str, Any]

HISTORY_PAGE_SIZE = 25


def define_audit_table(
    metadata: MetaData, *, name: str = "hxadmin_audit", schema: str | None = None
) -> Table:
    """Add hxadmin's audit table to application metadata, without issuing DDL."""
    return Table(
        name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("actor_id", Text, nullable=False),
        Column("view_identity", Text, nullable=False),
        Column("record_key", Text, nullable=False),
        Column("operation", String(6), nullable=False),
        Column("changes", JSON, nullable=False),
        Index(f"ix_{name}_record", "view_identity", "record_key", "id"),
        schema=schema,
    )


def snapshot(obj: Any, names: Sequence[str]) -> Snapshot:
    # Encoding now makes a detached copy of mutable values and preserves decimal precision.
    return jsonable_encoder(
        {name: getattr(obj, name) for name in names}, custom_encoder={Decimal: str}
    )


class AuditLog:
    def __init__(self, table: Table, actor: Callable[[Any], str]) -> None:
        self.table = table
        self.actor = actor

    def actor_id(self, user: Any) -> str:
        actor_id = self.actor(user)
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("audit_actor must return a non-empty string")
        return actor_id

    async def record(
        self,
        session: AsyncSession,
        *,
        actor_id: str,
        identity: str,
        key: str,
        operation: AuditOperation,
        before: Snapshot,
        after: Snapshot,
    ) -> None:
        changes = {}
        for name in before or after:
            previous, current = before.get(name), after.get(name)
            if operation != "update" or json.dumps(previous, sort_keys=True) != json.dumps(
                current, sort_keys=True
            ):
                changes[name] = {"before": previous, "after": current}
        if changes:
            await session.execute(
                self.table.insert().values(
                    occurred_at=datetime.now(UTC),
                    actor_id=actor_id,
                    view_identity=identity,
                    record_key=key,
                    operation=operation,
                    changes=changes,
                )
            )

    async def history(
        self, session: AsyncSession, identity: str, key: str, *, before: int | None
    ) -> Sequence[RowMapping]:
        c = self.table.c
        record = (c.view_identity == identity, c.record_key == key)
        # A recorded create or delete marks the start or end of one use of this key.
        boundary = (
            select(func.coalesce(func.max(c.id), 0))
            .where(*record, c.operation.in_(("create", "delete")))
            .scalar_subquery()
        )
        stmt = (
            select(c.id, c.occurred_at, c.actor_id, c.operation, c.changes)
            .where(*record, c.id >= boundary, c.operation != "delete")
            .order_by(c.id.desc())
            .limit(HISTORY_PAGE_SIZE + 1)
        )
        if before is not None:
            stmt = stmt.where(c.id < before)
        return (await session.execute(stmt)).mappings().all()
