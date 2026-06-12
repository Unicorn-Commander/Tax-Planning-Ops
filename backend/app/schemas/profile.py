from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

PrimaryObjective = Literal[
    "minimize_current_tax",
    "minimize_lifetime_tax",
    "maximize_retirement",
    "wealth_transfer",
    "charitable_legacy",
    "no_preference",
]
LiquidityEvent = Literal[
    "none", "business_sale", "equity_compensation", "real_estate", "inheritance", "other"
]
CharitableIntent = Literal["none", "low", "moderate", "high", "legacy"]
EstatePriority = Literal["none", "moderate", "high"]
RothPreference = Literal["prefer_roth", "prefer_traditional", "no_preference", "advisor_optimize"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
CashFlowSensitivity = Literal["low", "medium", "high"]
BusinessSuccession = Literal["none", "sell_external", "transfer_family", "esop", "undecided"]


class PlanningProfileIn(BaseModel):
    primary_objective: PrimaryObjective = "no_preference"
    retirement_target_year: int | None = None
    liquidity_event: LiquidityEvent = "none"
    liquidity_event_year: int | None = None
    liquidity_event_amount_cents: int = 0
    charitable_intent: CharitableIntent = "none"
    annual_giving_cents: int = 0
    estate_priority: EstatePriority = "none"
    planned_relocation_state: str | None = None
    relocation_year: int | None = None
    roth_preference: RothPreference = "no_preference"
    risk_tolerance: RiskTolerance = "moderate"
    cash_flow_sensitivity: CashFlowSensitivity = "medium"
    education_funding: bool = False
    business_succession: BusinessSuccession = "none"
    notes: str | None = None


class PlanningProfileOut(PlanningProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    client_id: UUID
