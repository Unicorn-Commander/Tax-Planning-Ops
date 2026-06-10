from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

QuarterlyMethod = Literal["even", "annualized"]
SafeHarborBasis = Literal["90_current", "100_prior", "110_prior_high_agi"]


class QuarterlyConfig(BaseModel):
    current_year_rate: Decimal
    prior_year_rate: Decimal
    high_agi_prior_year_rate: Decimal
    high_agi_threshold_cents: int
    due_dates: list[date]


class QuarterlyInput(BaseModel):
    projected_current_year_tax_cents: int
    prior_year_tax_cents: int
    prior_year_agi_cents: int
    annual_withholding_cents: int = 0
    method: QuarterlyMethod = "even"
    period_income_cents: list[int] = Field(default_factory=lambda: [0, 0, 0, 0])
    payments_made_cents: list[int] = Field(default_factory=lambda: [0, 0, 0, 0])
    config: QuarterlyConfig


class QuarterlyPayment(BaseModel):
    quarter: int
    due_date: date
    required_payment_cents: int
    payment_made_cents: int
    withholding_credit_cents: int
    unpaid_rollforward_cents: int
    remaining_cents: int
    status: str
    annualized_income_cents: int


class QuarterlyResult(BaseModel):
    safe_harbor_basis: SafeHarborBasis
    required_annual_payment_cents: int
    quarters: list[QuarterlyPayment]


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def safe_harbor_target(payload: QuarterlyInput) -> tuple[SafeHarborBasis, int]:
    targets: list[tuple[SafeHarborBasis, int]] = [
        (
            "90_current",
            _cents(
                Decimal(payload.projected_current_year_tax_cents)
                * payload.config.current_year_rate
            ),
        ),
        (
            "100_prior",
            _cents(Decimal(payload.prior_year_tax_cents) * payload.config.prior_year_rate),
        ),
    ]
    if payload.prior_year_agi_cents > payload.config.high_agi_threshold_cents:
        targets.append(
            (
                "110_prior_high_agi",
                _cents(
                    Decimal(payload.prior_year_tax_cents)
                    * payload.config.high_agi_prior_year_rate
                ),
            )
        )
    return min(targets, key=lambda item: item[1])


def compute_quarterly(payload: QuarterlyInput) -> QuarterlyResult:
    if len(payload.config.due_dates) != 4:
        raise ValueError("exactly four due dates are required")
    basis, annual_target = safe_harbor_target(payload)
    period_count = len(payload.config.due_dates)
    withholding_credit = _cents(Decimal(payload.annual_withholding_cents) / Decimal(period_count))
    quarters: list[QuarterlyPayment] = []
    rollforward = 0
    ytd_income = 0
    ytd_required_before_credits = 0
    for index in range(4):
        quarter = index + 1
        ytd_income += payload.period_income_cents[index]
        if payload.method == "annualized":
            annualized_income = _cents(
                Decimal(ytd_income) * Decimal(period_count) / Decimal(quarter)
            )
            ytd_required_before_credits = min(
                annual_target,
                _cents(Decimal(annual_target) * Decimal(quarter) / Decimal(period_count)),
            )
            if annualized_income > 0:
                total_income = max(sum(payload.period_income_cents), annualized_income)
                ytd_required_before_credits = _cents(
                    Decimal(annual_target) * Decimal(annualized_income) / Decimal(total_income)
                )
        else:
            annualized_income = sum(payload.period_income_cents)
            ytd_required_before_credits = _cents(
                Decimal(annual_target) * Decimal(quarter) / Decimal(period_count)
            )
        prior_required = sum(
            q.required_payment_cents + q.withholding_credit_cents for q in quarters
        )
        gross_due = max(ytd_required_before_credits - prior_required, 0)
        required = max(gross_due - withholding_credit, 0)
        paid = payload.payments_made_cents[index]
        remaining = max(required + rollforward - paid, 0)
        status = "paid" if remaining == 0 else "partial" if paid > 0 else "projected"
        quarters.append(
            QuarterlyPayment(
                quarter=quarter,
                due_date=payload.config.due_dates[index],
                required_payment_cents=required,
                payment_made_cents=paid,
                withholding_credit_cents=withholding_credit,
                unpaid_rollforward_cents=rollforward,
                remaining_cents=remaining,
                status=status,
                annualized_income_cents=annualized_income,
            )
        )
        rollforward = remaining
    return QuarterlyResult(
        safe_harbor_basis=basis,
        required_annual_payment_cents=annual_target,
        quarters=quarters,
    )
