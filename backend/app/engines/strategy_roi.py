from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

SavingsMethod = Literal["amount_x_effective_rate", "manual", "amount_x_custom_rate"]


class StrategyConfig(BaseModel):
    name: str
    savings_method: SavingsMethod
    custom_rate: Decimal | None = None
    statutory_cap_cents: int | None = None
    applicability_rules: dict[str, Any] = Field(default_factory=dict)


class StrategyROIInput(BaseModel):
    amount_cents: int
    effective_rate: Decimal
    manual_savings_cents: int | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    strategy: StrategyConfig


class StrategyROIResult(BaseModel):
    estimated_savings_cents: int
    effective_rate_used: Decimal
    rate_basis_used: str
    amount_used_cents: int
    cap_applied: bool
    applicable: bool
    reason: str | None = None


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _applicability(strategy: StrategyConfig, facts: dict[str, Any]) -> tuple[bool, str | None]:
    for key, expected in strategy.applicability_rules.items():
        if key == "min_agi_cents" and int(facts.get("agi_cents", 0)) < int(expected):
            return False, "AGI below required minimum"
        if key == "requires_schedule_c" and expected and not facts.get("has_schedule_c"):
            return False, "Schedule C not present"
    return True, None


def compute_strategy_roi(payload: StrategyROIInput) -> StrategyROIResult:
    applicable, reason = _applicability(payload.strategy, payload.facts)
    amount = max(payload.amount_cents, 0)
    cap_applied = False
    if (
        payload.strategy.statutory_cap_cents is not None
        and amount > payload.strategy.statutory_cap_cents
    ):
        amount = payload.strategy.statutory_cap_cents
        cap_applied = True

    if not applicable:
        return StrategyROIResult(
            estimated_savings_cents=0,
            effective_rate_used=payload.effective_rate,
            rate_basis_used="not_applicable",
            amount_used_cents=amount,
            cap_applied=cap_applied,
            applicable=False,
            reason=reason,
        )

    if payload.strategy.savings_method == "manual":
        return StrategyROIResult(
            estimated_savings_cents=max(payload.manual_savings_cents or 0, 0),
            effective_rate_used=payload.effective_rate,
            rate_basis_used="manual",
            amount_used_cents=amount,
            cap_applied=cap_applied,
            applicable=True,
        )
    if payload.strategy.savings_method == "amount_x_custom_rate":
        rate = payload.strategy.custom_rate or Decimal("0")
        basis = "custom_rate"
    else:
        rate = payload.effective_rate
        basis = "effective_rate"

    return StrategyROIResult(
        estimated_savings_cents=_round_cents(Decimal(amount) * rate),
        effective_rate_used=payload.effective_rate,
        rate_basis_used=basis,
        amount_used_cents=amount,
        cap_applied=cap_applied,
        applicable=True,
    )
