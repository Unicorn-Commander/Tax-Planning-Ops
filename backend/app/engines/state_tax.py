"""State income tax — config-driven, all 50 states via the same engine.

A state config carries its brackets (or a flat rate), standard deduction,
whether it taxes Social Security / retirement income, and any surtaxes (CA's 1%
mental-health tax over $1M, MA's 4% millionaire surtax, etc.). No-income-tax
states (TX/FL/WA/…) set has_income_tax=False.

For PLANNING, state taxable income ≈ the federal starting point (AGI or taxable
income) minus the state standard deduction and any income the state exempts.
This is an approximation — states have many conformity quirks — so every
subtraction is surfaced as an assumption. All money is integer cents; the 2025
state configs live in app/state_configs.py.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.engines.form1040 import RateBracket, bracket_walk

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class StateSurtax(BaseModel):
    name: str
    threshold_cents: int
    rate: Decimal
    applies_to: Literal["state_taxable_income", "federal_agi"] = "state_taxable_income"


class StateTaxConfig(BaseModel):
    state: str
    has_income_tax: bool = True
    flat_rate: Decimal | None = None  # if set, a flat-rate state
    brackets_by_status: dict[str, list[RateBracket]] = Field(default_factory=dict)
    standard_deduction_by_status: dict[str, int] = Field(default_factory=dict)
    taxes_social_security: bool = True
    taxes_retirement_income: bool = True
    surtaxes: list[StateSurtax] = Field(default_factory=list)
    starts_from: Literal["federal_agi", "federal_taxable_income"] = "federal_agi"


class StateTaxInput(BaseModel):
    filing_status: FilingStatus
    federal_agi_cents: int
    federal_taxable_income_cents: int = 0
    social_security_taxable_cents: int = 0  # taxable SS already in federal AGI
    retirement_income_cents: int = 0  # IRA/pension some states exempt


class StateTaxResult(BaseModel):
    state: str
    has_income_tax: bool
    state_taxable_income_cents: int
    base_tax_cents: int
    surtax_cents: int
    total_state_tax_cents: int
    marginal_rate: Decimal
    assumptions: list[str] = Field(default_factory=list)


def _dollars(value: Decimal) -> int:
    # State returns round the tax to whole dollars.
    return int((value / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def _status_key(config_map: dict[str, list[RateBracket]] | dict[str, int], status: str) -> str:
    if status in config_map:
        return status
    # Single brackets/deductions cover single/hoh/qss/mfs by default.
    return "mfj" if status == "mfj" else "single"


def calculate_state_tax(inputs: StateTaxInput, config: StateTaxConfig) -> StateTaxResult:
    if not config.has_income_tax:
        return StateTaxResult(
            state=config.state, has_income_tax=False, state_taxable_income_cents=0,
            base_tax_cents=0, surtax_cents=0, total_state_tax_cents=0,
            marginal_rate=Decimal("0"),
            assumptions=[f"{config.state} has no state income tax."],
        )

    assumptions: list[str] = []
    base = (
        inputs.federal_taxable_income_cents
        if config.starts_from == "federal_taxable_income"
        else inputs.federal_agi_cents
    )
    subtractions = config.standard_deduction_by_status.get(
        _status_key(config.standard_deduction_by_status, inputs.filing_status), 0
    )
    if not config.taxes_social_security and inputs.social_security_taxable_cents > 0:
        subtractions += inputs.social_security_taxable_cents
        assumptions.append(f"{config.state} excludes Social Security benefits from state income.")
    if not config.taxes_retirement_income and inputs.retirement_income_cents > 0:
        subtractions += inputs.retirement_income_cents
        assumptions.append(f"{config.state} excludes retirement/pension income.")

    state_taxable = max(base - subtractions, 0)

    if config.flat_rate is not None:
        base_tax = _dollars(Decimal(state_taxable) * config.flat_rate)
        marginal = config.flat_rate
    else:
        brackets = config.brackets_by_status.get(
            _status_key(config.brackets_by_status, inputs.filing_status), []
        )
        if brackets:
            raw, marginal = bracket_walk(state_taxable, brackets)
            base_tax = _dollars(Decimal(raw))
        else:
            base_tax, marginal = 0, Decimal("0")

    surtax = 0
    for s in config.surtaxes:
        applies_base = (
            state_taxable if s.applies_to == "state_taxable_income" else inputs.federal_agi_cents
        )
        over = max(applies_base - s.threshold_cents, 0)
        if over > 0:
            surtax += _dollars(Decimal(over) * s.rate)
            marginal = marginal + s.rate  # top marginal includes the surtax

    assumptions.append(
        f"State taxable income approximated as {config.starts_from} less the {config.state} "
        "standard deduction; state-specific add/subtractions beyond SS/retirement not modeled."
    )
    return StateTaxResult(
        state=config.state, has_income_tax=True,
        state_taxable_income_cents=state_taxable,
        base_tax_cents=base_tax, surtax_cents=surtax,
        total_state_tax_cents=base_tax + surtax, marginal_rate=marginal,
        assumptions=assumptions,
    )
