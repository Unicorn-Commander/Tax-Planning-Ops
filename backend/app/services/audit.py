from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tax_year import AuditJournal


def compute_audit_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
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
        select(AuditJournal).where(AuditJournal.workspace_id == workspace_id).order_by(
            AuditJournal.created_at.desc()
        )
    )
    prev_hash = previous.hash if previous else None
    event_hash = compute_audit_hash(prev_hash, payload)
    event = AuditJournal(
        workspace_id=workspace_id,
        created_at=datetime.now(UTC),
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
        .order_by(AuditJournal.created_at.asc())
    )
    previous: str | None = None
    for event in result.scalars():
        if event.prev_hash != previous:
            return False
        if compute_audit_hash(event.prev_hash, event.payload) != event.hash:
            return False
        previous = event.hash
    return True
