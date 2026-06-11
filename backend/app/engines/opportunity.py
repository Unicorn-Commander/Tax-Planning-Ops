"""Deterministic tax-planning opportunity scan.

A small catalog of STRUCTURAL strategies, each expressed as a mutation of the
Form 1040 inputs (which input field it touches), scored by re-running the real
federal engine (`recompute_scenario`) — never by a flat rate and never by a
language model. The dollar figures here are authoritative; the planning agent's
LLM layer only narrates them.

No new tax-year constants live here: each strategy models "what if the client
moved $X" for an advisor-chosen illustrative amount, and the engine returns the
true marginal effect (bracket crossings, the standard-vs-itemized floor, QBI
headroom, NIIT exposure, etc.). Contribution LIMITS (e.g. §402(g)) are an
advisor input, not baked in — so this stays correct across tax years.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from pydantic import BaseModel, Field

from app.engines.form1040 import Form1040Inputs, Form1040Result, TaxConfig, calculate_form1040
from app.engines.multiyear import InputMutation, recompute_scenario

DEFAULT_ILLUSTRATIVE_CENTS = 1_000_000  # $10,000 — a round modeling amount


class Opportunity(BaseModel):
    code: str
    name: str
    category: str
    citation: str
    illustrative_amount_cents: int
    estimated_tax_savings_cents: int  # positive = savings this year (real recompute)
    marginal_rate_used: Decimal
    eligibility_note: str
    facts: dict[str, int | str] = Field(default_factory=dict)


class _CatalogEntry(BaseModel):
    code: str
    name: str
    category: str
    citation: str
    eligibility_note: str
    # (inputs, base_result) -> applicable?
    applies: Callable[[Form1040Inputs, Form1040Result], bool]
    # illustrative amount (cents) -> mutation
    mutation: Callable[[int], InputMutation]

    model_config = {"arbitrary_types_allowed": True}


CATALOG: list[_CatalogEntry] = [
    _CatalogEntry(
        code="retirement_deferral_401k",
        name="Pre-tax retirement deferral (401(k)/403(b))",
        category="retirement",
        citation="IRC §402(g)",
        eligibility_note=(
            "Requires an employer plan with deferral room; amount capped by the "
            "annual elective-deferral limit."
        ),
        applies=lambda i, r: i.wages_cents > 0,
        # A pre-tax elective deferral reduces Box-1 taxable wages.
        mutation=lambda amt: InputMutation(delta_fields={"wages_cents": -amt}),
    ),
    _CatalogEntry(
        code="traditional_ira",
        name="Deductible traditional IRA contribution",
        category="retirement",
        citation="IRC §219",
        eligibility_note=(
            "Deductibility phases out with an active employer plan and higher MAGI; "
            "advisor must confirm."
        ),
        applies=lambda i, r: (i.wages_cents > 0 or i.schedule_1_income_cents > 0),
        mutation=lambda amt: InputMutation(delta_fields={"adjustments_cents": amt}),
    ),
    _CatalogEntry(
        code="hsa_contribution",
        name="Health Savings Account contribution",
        category="health",
        citation="IRC §223",
        eligibility_note="Requires HDHP coverage; amount capped by the annual HSA limit.",
        applies=lambda i, r: True,
        mutation=lambda amt: InputMutation(delta_fields={"adjustments_cents": amt}),
    ),
    _CatalogEntry(
        code="charitable_bunching",
        name="Charitable bunching (itemize this year)",
        category="charitable",
        citation="IRC §170",
        eligibility_note=(
            "Only saves tax when bunched itemized deductions exceed the standard deduction."
        ),
        applies=lambda i, r: True,
        mutation=lambda amt: InputMutation(delta_fields={"itemized_deduction_cents": amt}),
    ),
    _CatalogEntry(
        code="tax_loss_harvesting",
        name="Tax-loss harvesting against realized gains",
        category="investments",
        citation="IRC §1211/§1212",
        eligibility_note="Requires unrealized losses; wash-sale rules apply.",
        applies=lambda i, r: i.capital_gain_loss_cents > 0
        or (i.net_long_term_capital_gain_cents or 0) > 0,
        mutation=lambda amt: InputMutation(delta_fields={"capital_gain_loss_cents": -amt}),
    ),
]


def find_opportunities(
    inputs: Form1040Inputs,
    config: TaxConfig,
    *,
    illustrative_amount_cents: int = DEFAULT_ILLUSTRATIVE_CENTS,
    include_zero: bool = False,
) -> list[Opportunity]:
    """Score every applicable catalog strategy with a real engine recompute.

    Returns opportunities sorted by estimated savings (descending). Strategies
    that produce no savings at the illustrative amount (e.g. charitable bunching
    below the standard-deduction floor) are dropped unless `include_zero`."""
    base = calculate_form1040(inputs, config)
    out: list[Opportunity] = []
    for entry in CATALOG:
        if not entry.applies(inputs, base):
            continue
        recompute = recompute_scenario(
            inputs,
            config,
            entry.mutation(illustrative_amount_cents),
            base_result=base,
        )
        savings = -recompute.tax_delta_cents  # delta negative = savings
        if savings <= 0 and not include_zero:
            continue
        out.append(
            Opportunity(
                code=entry.code,
                name=entry.name,
                category=entry.category,
                citation=entry.citation,
                illustrative_amount_cents=illustrative_amount_cents,
                estimated_tax_savings_cents=savings,
                marginal_rate_used=recompute.marginal_rate_base,
                eligibility_note=entry.eligibility_note,
                facts={
                    "current_agi_cents": base.agi_cents,
                    "current_total_tax_cents": base.total_tax_cents,
                    "current_marginal_rate": str(base.marginal_rate),
                },
            )
        )
    out.sort(key=lambda o: o.estimated_tax_savings_cents, reverse=True)
    return out
