"""Child Tax Credit + Credit for Other Dependents + refundable ACTC.

Schedule 8812, tax year 2025 (post-OBBBA: CTC raised to $2,200/qualifying
child, indexed going forward; ODC $500). Nonrefundable CTC+ODC offsets tax;
the refundable Additional CTC (ACTC) is capped at $1,700/qualifying child and
the 15%-of-earned-income-over-$2,500 formula.

Scope note: the 3+-qualifying-children alternate ACTC method (Schedule 8812
Part II-B, using SS/Medicare taxes) is intentionally out of scope — for
planning the basic 15% formula governs the common case; the engine flags when
that alternate could apply. All money is integer cents.
"""

from __future__ import annotations

import math
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class CTCConfig(BaseModel):
    tax_year: int
    ctc_per_child_cents: int
    odc_per_dependent_cents: int
    phaseout_threshold_mfj_cents: int
    phaseout_threshold_other_cents: int
    phaseout_step_cents: int  # excess rounded UP to this step…
    phaseout_per_step_cents: int  # …then this much credit lost per step
    refundable_cap_per_child_cents: int
    earned_income_floor_cents: int
    earned_income_rate: Decimal


def ty2025_ctc_config() -> CTCConfig:
    return CTCConfig(
        tax_year=2025,
        ctc_per_child_cents=220_000,  # $2,200 (OBBBA)
        odc_per_dependent_cents=50_000,  # $500
        phaseout_threshold_mfj_cents=40_000_000,  # $400,000
        phaseout_threshold_other_cents=20_000_000,  # $200,000
        phaseout_step_cents=100_000,  # $1,000
        phaseout_per_step_cents=5_000,  # $50 per $1,000 (= 5%)
        refundable_cap_per_child_cents=170_000,  # $1,700
        earned_income_floor_cents=250_000,  # $2,500
        earned_income_rate=Decimal("0.15"),
    )


class CTCInput(BaseModel):
    filing_status: FilingStatus
    qualifying_children: int = 0
    other_dependents: int = 0
    magi_cents: int = 0
    tax_liability_cents: int = 0  # tax before CTC (the credit-limit)
    earned_income_cents: int = 0


class CTCResult(BaseModel):
    credit_before_phaseout_cents: int
    phaseout_reduction_cents: int
    credit_after_phaseout_cents: int
    nonrefundable_ctc_odc_cents: int
    refundable_actc_cents: int
    assumptions: list[str] = Field(default_factory=list)


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_ctc(inputs: CTCInput, config: CTCConfig) -> CTCResult:
    qc = max(inputs.qualifying_children, 0)
    odc = max(inputs.other_dependents, 0)
    ctc = qc * config.ctc_per_child_cents
    odc_credit = odc * config.odc_per_dependent_cents
    combined = ctc + odc_credit

    threshold = (
        config.phaseout_threshold_mfj_cents
        if inputs.filing_status == "mfj"
        else config.phaseout_threshold_other_cents
    )
    excess = max(inputs.magi_cents - threshold, 0)
    # Round the excess UP to the next whole step ($1,000), then lose $50/step.
    steps = math.ceil(excess / config.phaseout_step_cents) if excess > 0 else 0
    phaseout = steps * config.phaseout_per_step_cents
    after_phaseout = max(combined - phaseout, 0)

    tax = max(inputs.tax_liability_cents, 0)
    nonrefundable = min(after_phaseout, tax)

    remaining = after_phaseout - nonrefundable
    max_actc = qc * config.refundable_cap_per_child_cents
    earned_over_floor = max(inputs.earned_income_cents - config.earned_income_floor_cents, 0)
    earned_formula = int(
        (Decimal(earned_over_floor) * config.earned_income_rate).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
    )
    actc = max(min(remaining, max_actc, earned_formula), 0)

    assumptions: list[str] = []
    if qc >= 3 and actc == earned_formula and earned_formula < min(remaining, max_actc):
        assumptions.append(
            "actc_3plus_children_alternate_not_modeled: with 3+ qualifying children the "
            "Schedule 8812 Part II-B SS/Medicare-tax method can yield a larger refundable "
            "credit; only the basic 15% earned-income method is computed here."
        )

    return CTCResult(
        credit_before_phaseout_cents=combined,
        phaseout_reduction_cents=phaseout,
        credit_after_phaseout_cents=after_phaseout,
        nonrefundable_ctc_odc_cents=nonrefundable,
        refundable_actc_cents=actc,
        assumptions=assumptions,
    )
