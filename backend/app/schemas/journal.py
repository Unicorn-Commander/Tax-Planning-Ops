"""Schemas for the audit-journal read tail (spec §9.5).

The journal is written append-only with a verifiable hash chain; these shapes
expose a scoped, paginated READ of that tail (it is otherwise write-only) for
the Desk ticker and the Staff traffic feed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JournalEventOut(BaseModel):
    """A single audit-journal row as stored, including its chain hashes."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    event_type: str
    actor_uc_uid: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    hash: str
    prev_hash: str | None


class JournalStatusOut(BaseModel):
    """Summary of the workspace's journal: size, the newest event's hash/time,
    and whether the hash chain still verifies."""

    count: int
    latest_hash: str | None
    latest_at: datetime | None
    chain_intact: bool


class JournalTailOut(BaseModel):
    """The newest-first tail of events plus the chain status."""

    events: list[JournalEventOut]
    status: JournalStatusOut
