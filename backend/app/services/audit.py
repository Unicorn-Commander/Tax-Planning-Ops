from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tax_year import AuditJournal


def compute_audit_hash(
    prev_hash: str | None,
    *,
    event_type: str,
    actor_uc_uid: str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    created_at: datetime,
    payload: dict[str, Any],
) -> str:
    # Hash the full record, not just the payload, so actor/event/aggregate/
    # timestamp cannot be altered after the fact without breaking the chain.
    record = {
        "event_type": event_type,
        "actor_uc_uid": actor_uc_uid,
        "aggregate_type": aggregate_type,
        "aggregate_id": str(aggregate_id),
        "created_at": created_at.isoformat(),
        "payload": payload,
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash or ''}{canonical}".encode()).hexdigest()


async def append_audit_event(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> AuditJournal:
    previous = await db.scalar(
        select(AuditJournal)
        .where(AuditJournal.workspace_id == workspace_id)
        .order_by(AuditJournal.created_at.desc(), AuditJournal.id.desc())
    )
    prev_hash = previous.hash if previous else None
    created_at = datetime.now(UTC)
    event_hash = compute_audit_hash(
        prev_hash,
        event_type=event_type,
        actor_uc_uid=actor_uc_uid,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        created_at=created_at,
        payload=payload,
    )
    event = AuditJournal(
        workspace_id=workspace_id,
        created_at=created_at,
        actor_uc_uid=actor_uc_uid,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        prev_hash=prev_hash,
        hash=event_hash,
    )
    db.add(event)
    await db.flush()
    return event


async def verify_audit_chain(db: AsyncSession, workspace_id: UUID) -> bool:
    result = await db.execute(
        select(AuditJournal)
        .where(AuditJournal.workspace_id == workspace_id)
        .order_by(AuditJournal.created_at.asc(), AuditJournal.id.asc())
    )
    previous: str | None = None
    for event in result.scalars():
        if event.prev_hash != previous:
            return False
        expected = compute_audit_hash(
            event.prev_hash,
            event_type=event.event_type,
            actor_uc_uid=event.actor_uc_uid,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            created_at=event.created_at,
            payload=event.payload,
        )
        if expected != event.hash:
            return False
        previous = event.hash
    return True
