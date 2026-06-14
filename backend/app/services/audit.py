from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tax_year import AuditJournal

# Hard cap on how many journal rows a single read can pull back, regardless of
# what the caller asks for — the journal is unbounded and the read tail powers a
# ticker, not an export.
_MAX_JOURNAL_TAIL = 200


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


async def read_journal_tail(
    db: AsyncSession,
    workspace_id: UUID,
    *,
    limit: int = 20,
    before: datetime | None = None,
) -> list[AuditJournal]:
    """Return the newest-first tail of the workspace's audit journal.

    RLS already scopes the journal to the current workspace via the GUC; the
    explicit ``workspace_id`` filter is a defensive belt-and-suspenders so a
    misconfigured session can never leak another tenant's events. ``limit`` is
    clamped to ``[1, _MAX_JOURNAL_TAIL]``; pass ``before`` (a ``created_at``) to
    page backwards through older events.
    """
    bounded = max(1, min(int(limit), _MAX_JOURNAL_TAIL))
    stmt = (
        select(AuditJournal)
        .where(AuditJournal.workspace_id == workspace_id)
        .order_by(AuditJournal.created_at.desc(), AuditJournal.id.desc())
        .limit(bounded)
    )
    if before is not None:
        stmt = stmt.where(AuditJournal.created_at < before)
    result = await db.scalars(stmt)
    return list(result.all())


async def journal_status(db: AsyncSession, workspace_id: UUID) -> dict[str, Any]:
    """Summarize the workspace's journal: how many events, the newest event's
    hash/time, and whether the hash chain still verifies. ``chain_intact``
    re-runs the full ``verify_audit_chain`` so the ticker can surface tamper."""
    row = (
        await db.execute(
            select(
                func.count(AuditJournal.id),
                func.max(AuditJournal.created_at),
            ).where(AuditJournal.workspace_id == workspace_id)
        )
    ).one()
    count, latest_at = row
    latest_hash = None
    if count:
        latest_hash = await db.scalar(
            select(AuditJournal.hash)
            .where(AuditJournal.workspace_id == workspace_id)
            .order_by(AuditJournal.created_at.desc(), AuditJournal.id.desc())
            .limit(1)
        )
    return {
        "count": int(count or 0),
        "latest_hash": latest_hash,
        "latest_at": latest_at,
        "chain_intact": await verify_audit_chain(db, workspace_id),
    }
