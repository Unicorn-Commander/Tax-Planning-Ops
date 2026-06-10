from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class ComputeQuarterlyRequest(BaseModel):
    projected_current_year_tax_cents: int
    prior_year_tax_cents: int
    prior_year_agi_cents: int
    annual_withholding_cents: int = 0
    method: str = "even"
    period_income_cents: list[int] = [0, 0, 0, 0]
    payments_made_cents: list[int] = [0, 0, 0, 0]


class QuarterlyRecordOut(BaseModel):
    id: UUID
    quarter: int
    due_date: date
    required_payment_cents: int
    payment_made_cents: int
    unpaid_rollforward_cents: int
    status: str
    annualized_income_cents: int


class QuarterlyResultOut(BaseModel):
    safe_harbor_basis: str
    required_annual_payment_cents: int
    quarters: list[QuarterlyRecordOut]
