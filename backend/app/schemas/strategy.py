from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrategyLibraryIn(BaseModel):
    name: str
    category: str
    description: str
    client_facing_copy: str
    default_amount_cents: int | None = None
    savings_method: str = "amount_x_effective_rate"
    custom_rate: Decimal | None = None
    applicability_rules: dict[str, Any] = Field(default_factory=dict)
    statutory_cap_cents: int | None = None
    citation: str | None = None
    is_active: bool = True
    sort_order: int = 0
    tax_year_applicability: list[int] = Field(default_factory=list)


class StrategyLibraryOut(StrategyLibraryIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID


class AddClientStrategyRequest(BaseModel):
    strategy_id: UUID
    disposition: str = "recommended"
    amount_cents: int
    status_flag: str = "explore"
    advisor_note: str | None = None
    manual_savings_cents: int | None = None


class ClientStrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    client_tax_year_id: UUID
    strategy_id: UUID
    disposition: str
    amount_cents: int
    effective_rate_used: Decimal
    estimated_savings_cents: int
    status_flag: str
    advisor_note: str | None
