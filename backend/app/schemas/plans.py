from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class CreatePlanRequest(BaseModel):
    base_tax_year_id: UUID
    target_tax_year: int


class UpdateAssumptionsRequest(BaseModel):
    assumptions: dict[str, Any]


class ProjectionSnapshotRead(BaseModel):
    client_tax_year_id: UUID
    tax_year: int
    role: str
    inputs: dict[str, Any]
    assumptions: dict[str, Any]
    total_income_cents: int
    agi_cents: int
    taxable_income_cents: int
    total_tax_cents: int
    marginal_rate: str
    effective_rate: str
    delta_total_tax_cents: int | None = None


class PlanProjectionRead(BaseModel):
    current: ProjectionSnapshotRead
    next_year: ProjectionSnapshotRead
