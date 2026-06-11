"""Form 2210 — underpayment of estimated tax penalty, tax year 2025.

Regular method (Part III): required annual payment is the lesser of 90% of the
current-year tax or the prior-year safe harbor (100%, or 110% if prior-year AGI
exceeds $150,000 / $75,000 MFS), split into four equal installments. Each
underpaid installment accrues interest at the IRS underpayment rate from its due
date to the 4/15 filing deadline. For 2025 the individual underpayment rate is a
flat 7%/yr across the entire penalty window (confirmed Q1 2025–Q1 2026), so no
mid-period rate split is needed.

Out of scope (correctly): Schedule AI annualized-income method and the actual
withholding-date election (Box D). All money is integer cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]
SafeHarborBasis = Literal["current_90", "prior_100", "prior_110"]


class Form2210Config(BaseModel):
    tax_year: int
    current_year_rate: Decimal = Decimal("0.90")
    prior_year_rate: Decimal = Decimal("1.00")
    prior_year_high_rate: Decimal = Decimal("1.10")
    high_agi_threshold_cents: int = 15_000_000  # $150,000 ($75,000 MFS)
    high_agi_threshold_mfs_cents: int = 7_500_000
    de_minimis_cents: int = 100_000  # $1,000 balance-after-withholding gate
    underpayment_rate: Decimal = Decimal("0.07")  # 2025 flat annual rate
    installment_fraction: Decimal = Decimal("0.25")
    # Days from each installment due date to the 4/15/2026 penalty end (non-leap).
    days_to_deadline: list[int] = Field(default_factory=lambda: [365, 304, 212, 90])


def ty2025_form2210_config() -> Form2210Config:
    return Form2210Config(tax_year=2025)


class Form2210Input(BaseModel):
    filing_status: FilingStatus
    current_year_total_tax_cents: int
    prior_year_total_tax_cents: int
    prior_year_agi_cents: int
    annual_withholding_cents: int = 0
    estimated_payments_by_quarter_cents: list[int] = Field(default_factory=lambda: [0, 0, 0, 0])


class InstallmentPenalty(BaseModel):
    quarter: int
    required_installment_cents: int
    paid_cents: int
    underpayment_cents: int
    days: int
    penalty_cents: int  # precise (to the cent)


class Form2210Result(BaseModel):
    penalty_owed: bool
    total_penalty_cents: int  # rounded to whole dollars per the form
    required_annual_payment_cents: int
    safe_harbor_basis: SafeHarborBasis
    installments: list[InstallmentPenalty]
    de_minimis_applied: bool
    assumptions: list[str] = Field(default_factory=list)


def _round_half_up(value: Decimal, quantum: str = "1") -> int:
    return int(value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP))


def calculate_form2210(inputs: Form2210Input, config: Form2210Config) -> Form2210Result:
    balance_after_withholding = (
        inputs.current_year_total_tax_cents - inputs.annual_withholding_cents
    )

    threshold = (
        config.high_agi_threshold_mfs_cents
        if inputs.filing_status == "mfs"
        else config.high_agi_threshold_cents
    )
    high_income = inputs.prior_year_agi_cents > threshold
    prior_rate = config.prior_year_high_rate if high_income else config.prior_year_rate

    current_target = _round_half_up(
        Decimal(inputs.current_year_total_tax_cents) * config.current_year_rate
    )
    prior_target = _round_half_up(Decimal(inputs.prior_year_total_tax_cents) * prior_rate)

    if current_target <= prior_target:
        required_annual = current_target
        basis: SafeHarborBasis = "current_90"
    else:
        required_annual = prior_target
        basis = "prior_110" if high_income else "prior_100"

    required_installment = _round_half_up(
        Decimal(required_annual) * config.installment_fraction
    )
    withholding_per_quarter = _round_half_up(Decimal(inputs.annual_withholding_cents) / Decimal(4))

    # De minimis: no penalty if the balance after withholding is under $1,000.
    if balance_after_withholding < config.de_minimis_cents:
        return Form2210Result(
            penalty_owed=False,
            total_penalty_cents=0,
            required_annual_payment_cents=required_annual,
            safe_harbor_basis=basis,
            installments=[],
            de_minimis_applied=True,
        )

    est = list(inputs.estimated_payments_by_quarter_cents) + [0, 0, 0, 0]
    installments: list[InstallmentPenalty] = []
    total_penalty = Decimal("0")
    carryover = 0  # overpayment carried to the next installment
    for q in range(4):
        paid = withholding_per_quarter + est[q] + carryover
        underpayment = max(required_installment - paid, 0)
        carryover = max(paid - required_installment, 0)
        days = config.days_to_deadline[q]
        penalty = Decimal(underpayment) * config.underpayment_rate * Decimal(days) / Decimal(365)
        total_penalty += penalty
        installments.append(
            InstallmentPenalty(
                quarter=q + 1,
                required_installment_cents=required_installment,
                paid_cents=paid,
                underpayment_cents=underpayment,
                days=days,
                penalty_cents=_round_half_up(penalty),
            )
        )

    # The form rounds the penalty to whole dollars.
    total_dollars = _round_half_up(total_penalty / Decimal(100))
    total_penalty_cents = total_dollars * 100
    return Form2210Result(
        penalty_owed=total_penalty_cents > 0,
        total_penalty_cents=total_penalty_cents,
        required_annual_payment_cents=required_annual,
        safe_harbor_basis=basis,
        installments=installments,
        de_minimis_applied=False,
    )
