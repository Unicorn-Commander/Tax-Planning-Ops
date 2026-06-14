from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StrategistRunOut(BaseModel):
    """One immutable AI-strategist run (engine findings + draft memo + totals)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_tax_year_id: UUID
    snapshot_id: UUID | None
    findings: list[dict[str, Any]]
    memo_text: str | None
    current_total_tax_cents: int
    total_savings_identified_cents: int
    marginal_rate: Decimal
    objectives_summary: str | None
    trajectory: dict[str, Any]
    disclaimer: str | None
    payload_hash: str
    actor_uc_uid: str
    created_at: datetime


class MemoOut(BaseModel):
    """One version of an advisor memo (draft or sealed)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_tax_year_id: UUID
    strategist_run_id: UUID | None
    version: int
    body_md: str
    status: str
    signed_by: str | None
    signed_at: datetime | None
    content_hash: str | None
    audit_event_id: UUID | None
    supersedes_version: int | None
    created_at: datetime
    updated_at: datetime


class MemoVersionSummary(BaseModel):
    """A compact entry for the version history list."""

    model_config = ConfigDict(from_attributes=True)

    version: int
    status: str
    signed_at: datetime | None
    created_at: datetime


class MemoState(BaseModel):
    """The full memo picture for a tax year: the working/latest memo, the
    version history, and the run the latest memo was built from."""

    latest_memo: MemoOut | None
    versions: list[MemoVersionSummary]
    latest_run: StrategistRunOut | None


class MemoSaveIn(BaseModel):
    """Advisor edit to the working draft body."""

    body_md: str


class PendingMemoOut(BaseModel):
    """A draft memo awaiting sign-off, with enough client context to render the
    queue without a second lookup."""

    memo_id: UUID
    client_tax_year_id: UUID
    client_name: str
    tax_year: int
    version: int
    created_at: datetime
    total_savings_identified_cents: int | None


class RedlineOut(BaseModel):
    """A new memo version against the prior signed version it supersedes, with
    both bodies and both runs' findings so the UI can diff narrative + numbers.
    The base side is null when nothing signed precedes this version."""

    base_version: int | None
    base_body: str | None
    new_version: int
    new_body: str
    new_findings: list[dict[str, Any]]
    base_findings: list[dict[str, Any]] | None
