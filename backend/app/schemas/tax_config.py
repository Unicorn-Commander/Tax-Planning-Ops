from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TaxBracketRowIn(BaseModel):
    lower_bound_cents: int
    upper_bound_cents: int | None = None
    rate: Decimal
    ordinal: int


class TaxBracketSetIn(BaseModel):
    workspace_id: UUID | None = None
    tax_year: int
    jurisdiction: str = "federal"
    filing_status: str
    standard_deduction_cents: int
    auxiliary_schedules: dict[str, Any] = {}
    notes: str | None = None
    rows: list[TaxBracketRowIn]


class TaxBracketRowOut(TaxBracketRowIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bracket_set_id: UUID


class TaxBracketSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    tax_year: int
    jurisdiction: str
    filing_status: str
    standard_deduction_cents: int
    auxiliary_schedules: dict[str, Any]
    notes: str | None
    rows: list[TaxBracketRowOut] = []
