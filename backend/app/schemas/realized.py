"""Schemas for realized reconciliation — the renewal number (spec §9.7).

What a planned strategy ACTUALLY delivered, measured against next year's return
or the client's books, vs. the plan estimate. ``planned_savings_cents`` is locked
from the strategy estimate (or an explicit advisor input) at reconciliation time;
``realized_savings_cents`` is the operator-supplied measured actual. ``variance``
is realized minus planned — the per-strategy renewal signal — and the workspace
rollup sums it into the Book's realized counter. Money is integer cents.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RealizeIn(BaseModel):
    """Reconcile an outcome against a plan year.

    ``planned_savings_cents`` is the plan estimate to measure against: if given
    it's used verbatim; otherwise, when ``client_strategy_id`` is set, the
    service locks it from that strategy's ``estimated_savings_cents`` (never
    fabricated). ``realized_*`` is the measured actual the advisor supplies.
    """

    client_strategy_id: UUID | None = None
    realized_tax_year: int = Field(ge=1900, le=2100)
    planned_savings_cents: int | None = None
    realized_savings_cents: int | None = None
    realized_amount_cents: int | None = None
    # How the actual was sourced.
    basis: str = "manual"
    source_ref: str | None = None
    source_detail: dict[str, Any] | None = None
    note: str | None = None


class RealizedOutcomeOut(BaseModel):
    """A reconciled outcome as stored, plus the computed ``variance_cents``
    (realized − planned), present only once a realized figure is recorded."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_tax_year_id: UUID
    client_strategy_id: UUID | None
    realized_tax_year: int
    planned_savings_cents: int
    realized_savings_cents: int | None
    realized_amount_cents: int | None
    basis: str
    source_ref: str | None
    source_detail: dict[str, Any] | None
    reconciled_by: str | None
    reconciled_at: datetime | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    # realized − planned; None until an actual is recorded. Computed, never stored.
    variance_cents: int | None = None

    @model_validator(mode="after")
    def _compute_variance(self) -> RealizedOutcomeOut:
        if self.realized_savings_cents is not None:
            self.variance_cents = self.realized_savings_cents - self.planned_savings_cents
        return self


class RealizedClientRow(BaseModel):
    """One client-tax-year line in the Book's realized rollup."""

    client_id: UUID
    client_name: str
    client_tax_year_id: UUID
    tax_year: int
    planned_cents: int
    realized_cents: int
    variance_cents: int
    outcome_count: int


class RealizedRollupOut(BaseModel):
    """The Book's realized counter: planned vs. realized across every
    reconciled outcome in the workspace, with a per-client breakdown."""

    total_planned_cents: int
    total_realized_cents: int
    total_variance_cents: int
    # realized / planned as a percentage string; "0.0%" when nothing is planned.
    realized_pct: str
    clients: list[RealizedClientRow]
