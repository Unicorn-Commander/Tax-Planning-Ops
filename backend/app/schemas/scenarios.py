"""Request/response models for the live planning (Lab) endpoints.

These expose the existing pure tax engines as what-if instruments WITH search
traces, so the Lab surface's recompute, EMR terrain, Roth crossover, and S-corp
salary curve are real engine recomputes — never flat `amount × rate` estimates.
All money is integer cents; every rate is a string of the engine's Decimal so no
precision is lost crossing JSON.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScenarioRecomputeIn(BaseModel):
    """A structural what-if: absolute sets and/or signed deltas (cents) applied
    to the client's current situation, then re-run through the engine."""

    set_fields: dict[str, int] = Field(default_factory=dict)
    delta_fields: dict[str, int] = Field(default_factory=dict)


class ScenarioRecomputeOut(BaseModel):
    base_total_tax_cents: int
    scenario_total_tax_cents: int
    tax_delta_cents: int  # scenario − base (negative = savings)
    agi_delta_cents: int
    taxable_income_delta_cents: int
    marginal_rate_base: str
    marginal_rate_scenario: str
    savings: bool


class EMRSweepIn(BaseModel):
    start_cents: int | None = None  # default: the field's current value
    step_cents: int = 500_000
    steps: int = 40
    field: str = "wages_cents"


class EMRPoint(BaseModel):
    income_cents: int
    total_tax_cents: int
    marginal_rate: str  # real effective marginal = Δtax(this→next) / step


class EMRSweepOut(BaseModel):
    field: str
    base_income_cents: int
    points: list[EMRPoint]
    true_next_dollar_rate: str  # Δtax for +$100 at base / 100
    nominal_marginal_rate: str  # the engine's statutory bracket rate at base
    cliff_overlays: list[dict[str, Any]] = Field(default_factory=list)


class RothOptimizeOut(BaseModel):
    recommended_conversion_cents: int
    tax_cost_cents: int
    effective_rate_on_conversion: str
    bracket_ceiling_cents: int | None
    irmaa_warning: str | None
    trace: list[dict[str, Any]] = Field(default_factory=list)


class ScorpOptimizeOut(BaseModel):
    optimal_salary_cents: int
    savings_vs_all_salary_cents: int
    qbi_deduction_at_optimal_cents: int
    curve: list[dict[str, Any]] = Field(default_factory=list)
