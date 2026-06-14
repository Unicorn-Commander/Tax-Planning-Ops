"""Schemas for implementation tasks — the 5-field contracts (spec §9.4) — and
the resolved statutory-deadline catalog entries."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TaskCreateIn(BaseModel):
    """Create a contract row. WHAT=title, WHO=owner, CASH=amount_cents,
    WHEN=due_date or statutory_key (the service resolves the date from the
    catalog when only a key is given). ``client_strategy_id`` links the task to
    the accepted strategy it implements."""

    title: str
    owner: str = "advisor"
    amount_cents: int | None = None
    due_date: datetime | None = None
    statutory_key: str | None = None
    client_strategy_id: UUID | None = None
    sort_order: int = 0
    note: str | None = None


class TaskUpdateIn(BaseModel):
    """Partial update — only the fields that are set are applied. Flipping
    ``status`` to 'done' with ``evidence_blob_key`` set stamps the evidence
    timestamp server-side."""

    title: str | None = None
    owner: str | None = None
    amount_cents: int | None = None
    due_date: datetime | None = None
    statutory_key: str | None = None
    status: str | None = None
    sort_order: int | None = None
    evidence_blob_key: str | None = None
    note: str | None = None


class TaskOut(BaseModel):
    """A contract row as stored."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_tax_year_id: UUID
    client_strategy_id: UUID | None
    title: str
    owner: str
    amount_cents: int | None
    due_date: datetime | None
    statutory_key: str | None
    status: str
    evidence_blob_key: str | None
    evidence_uploaded_at: datetime | None
    sort_order: int
    note: str | None
    created_at: datetime
    updated_at: datetime


class StatutoryDeadlineOut(BaseModel):
    """A catalog entry resolved to a calendar date for a given tax year."""

    key: str
    label: str
    citation: str
    due_date: date
