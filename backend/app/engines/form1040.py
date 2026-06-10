from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CENT = Decimal("1")
ZERO = Decimal("0")

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class RateBracket(BaseModel):
    lower_bound_cents: int
    upper_bound_cents: int | None
    rate: Decimal


class AuxiliaryConfig(BaseModel):
    ltcg_brackets: list[RateBracket] = Field(default_factory=list)
    niit_threshold_cents: int | None = None
    niit_rate: Decimal = ZERO
    additional_medicare_threshold_cents: int | None = None
    additional_medicare_rate: Decimal = ZERO
    capital_loss_limit_cents: int


class TaxConfig(BaseModel):
    tax_year: int
    filing_status: FilingStatus
    standard_deduction_cents: int
    ordinary_brackets: list[RateBracket]
    auxiliary: AuxiliaryConfig


class Form1040Inputs(BaseModel):
    filing_status: FilingStatus
    wages_cents: int = 0
    taxable_interest_cents: int = 0
    ordinary_dividends_cents: int = 0
    qualified_dividends_cents: int = 0
    ira_taxable_cents: int = 0
    pensions_taxable_cents: int = 0
    social_security_taxable_cents: int = 0
    capital_gain_loss_cents: int = 0
    schedule_1_income_cents: int = 0
    adjustments_cents: int = 0
    itemized_deduction_cents: int = 0
    qbi_deduction_cents: int = 0
    nonrefundable_credits_cents: int = 0
    withholding_cents: int = 0
    estimated_payments_cents: int = 0
    reported_agi_cents: int | None = None
    reported_taxable_income_cents: int | None = None
    reported_total_tax_cents: int | None = None
    reconciliation_tolerance_cents: int = 100


class ReconciliationItem(BaseModel):
    field: str
    computed_cents: int
    reported_cents: int
    delta_cents: int
    within_tolerance: bool


class Form1040Result(BaseModel):
    total_income_cents: int
    agi_cents: int
    deduction_cents: int
    qbi_deduction_cents: int
    taxable_income_cents: int
    ordinary_tax_cents: int
    preferential_tax_cents: int
    niit_cents: int
    additional_medicare_cents: int
    nonrefundable_credits_cents: int
    total_tax_cents: int
    marginal_rate: Decimal
    effective_rate: Decimal
    balance_due_cents: int
    reconciliation: list[ReconciliationItem]
    other_taxes: dict[str, int]


def cents(value: Decimal) -> int:
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def bracket_walk(amount_cents: int, brackets: list[RateBracket]) -> tuple[int, Decimal]:
    amount = max(amount_cents, 0)
    tax = ZERO
    marginal = ZERO
    for bracket in brackets:
        lower = bracket.lower_bound_cents
        upper = bracket.upper_bound_cents
        if amount <= lower:
            break
        taxable_in_bracket = amount - lower if upper is None else min(amount, upper) - lower
        if taxable_in_bracket <= 0:
            continue
        tax += Decimal(taxable_in_bracket) * bracket.rate
        marginal = bracket.rate
        if upper is not None and amount <= upper:
            break
    return cents(tax), marginal


def _preferential_tax(
    taxable_income_cents: int,
    ordinary_income_cents: int,
    preferential_income_cents: int,
    ltcg_brackets: list[RateBracket],
) -> int:
    preferential = max(min(preferential_income_cents, taxable_income_cents), 0)
    if preferential == 0:
        return 0
    stack_base = max(min(ordinary_income_cents, taxable_income_cents), 0)
    remaining = preferential
    tax = ZERO
    for bracket in ltcg_brackets:
        lower = bracket.lower_bound_cents
        upper = bracket.upper_bound_cents
        bracket_start = max(lower, stack_base)
        bracket_end = upper if upper is not None else stack_base + remaining
        available = max(bracket_end - bracket_start, 0)
        used = min(remaining, available)
        if used > 0:
            tax += Decimal(used) * bracket.rate
            remaining -= used
        if remaining == 0:
            break
    if remaining > 0 and ltcg_brackets:
        tax += Decimal(remaining) * ltcg_brackets[-1].rate
    return cents(tax)


def _reconcile(
    field: str,
    computed: int,
    reported: int | None,
    tolerance: int,
) -> list[ReconciliationItem]:
    if reported is None:
        return []
    delta = computed - reported
    return [
        ReconciliationItem(
            field=field,
            computed_cents=computed,
            reported_cents=reported,
            delta_cents=delta,
            within_tolerance=abs(delta) <= tolerance,
        )
    ]


def calculate_form1040(inputs: Form1040Inputs, config: TaxConfig) -> Form1040Result:
    if inputs.filing_status != config.filing_status:
        raise ValueError("input filing status does not match tax config")

    capital_gain_loss = max(
        inputs.capital_gain_loss_cents,
        -config.auxiliary.capital_loss_limit_cents,
    )
    total_income = (
        inputs.wages_cents
        + inputs.taxable_interest_cents
        + inputs.ordinary_dividends_cents
        + inputs.ira_taxable_cents
        + inputs.pensions_taxable_cents
        + inputs.social_security_taxable_cents
        + capital_gain_loss
        + inputs.schedule_1_income_cents
    )
    agi = total_income - inputs.adjustments_cents
    deduction = max(config.standard_deduction_cents, inputs.itemized_deduction_cents)
    qbi = max(inputs.qbi_deduction_cents, 0)
    taxable_income = max(agi - deduction - qbi, 0)

    preferential_income = max(
        min(inputs.qualified_dividends_cents + max(capital_gain_loss, 0), taxable_income),
        0,
    )
    ordinary_taxable = max(taxable_income - preferential_income, 0)
    ordinary_tax, marginal = bracket_walk(ordinary_taxable, config.ordinary_brackets)
    pref_tax = _preferential_tax(
        taxable_income,
        ordinary_taxable,
        preferential_income,
        config.auxiliary.ltcg_brackets,
    )

    investment_income = max(
        inputs.taxable_interest_cents + inputs.ordinary_dividends_cents + max(capital_gain_loss, 0),
        0,
    )
    niit_base = 0
    if config.auxiliary.niit_threshold_cents is not None:
        niit_base = min(
            investment_income,
            max(agi - config.auxiliary.niit_threshold_cents, 0),
        )
    niit = cents(Decimal(niit_base) * config.auxiliary.niit_rate)

    additional_medicare_base = 0
    if config.auxiliary.additional_medicare_threshold_cents is not None:
        additional_medicare_base = max(
            inputs.wages_cents - config.auxiliary.additional_medicare_threshold_cents,
            0,
        )
    additional_medicare = cents(
        Decimal(additional_medicare_base) * config.auxiliary.additional_medicare_rate
    )

    tax_before_credits = ordinary_tax + pref_tax + niit + additional_medicare
    total_tax = max(tax_before_credits - max(inputs.nonrefundable_credits_cents, 0), 0)
    effective_rate = ZERO if total_income <= 0 else Decimal(total_tax) / Decimal(total_income)
    payments = inputs.withholding_cents + inputs.estimated_payments_cents

    reconciliation: list[ReconciliationItem] = []
    reconciliation.extend(
        _reconcile(
            "agi",
            agi,
            inputs.reported_agi_cents,
            inputs.reconciliation_tolerance_cents,
        )
    )
    reconciliation.extend(
        _reconcile(
            "taxable_income",
            taxable_income,
            inputs.reported_taxable_income_cents,
            inputs.reconciliation_tolerance_cents,
        )
    )
    reconciliation.extend(
        _reconcile(
            "total_tax",
            total_tax,
            inputs.reported_total_tax_cents,
            inputs.reconciliation_tolerance_cents,
        )
    )

    return Form1040Result(
        total_income_cents=total_income,
        agi_cents=agi,
        deduction_cents=deduction,
        qbi_deduction_cents=qbi,
        taxable_income_cents=taxable_income,
        ordinary_tax_cents=ordinary_tax,
        preferential_tax_cents=pref_tax,
        niit_cents=niit,
        additional_medicare_cents=additional_medicare,
        nonrefundable_credits_cents=max(inputs.nonrefundable_credits_cents, 0),
        total_tax_cents=total_tax,
        marginal_rate=marginal,
        effective_rate=effective_rate,
        balance_due_cents=total_tax - payments,
        reconciliation=reconciliation,
        other_taxes={
            "niit_cents": niit,
            "additional_medicare_cents": additional_medicare,
        },
    )


class BracketValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_matches_errors(self) -> BracketValidationResult:
        self.valid = not self.errors
        return self


def validate_brackets(brackets: list[RateBracket]) -> BracketValidationResult:
    errors: list[str] = []
    if not brackets:
        return BracketValidationResult(valid=False, errors=["at least one bracket is required"])
    sorted_rows = sorted(brackets, key=lambda row: row.lower_bound_cents)
    if sorted_rows[0].lower_bound_cents != 0:
        errors.append("first bracket must start at zero")
    previous_upper: int | None = None
    previous_rate = ZERO
    open_ended = 0
    for index, row in enumerate(sorted_rows):
        if row.rate < previous_rate:
            errors.append("rates must be monotonic")
        previous_rate = row.rate
        if row.upper_bound_cents is None:
            open_ended += 1
        elif row.upper_bound_cents <= row.lower_bound_cents:
            errors.append("upper bound must exceed lower bound")
        if index > 0 and row.lower_bound_cents != previous_upper:
            errors.append("brackets must be contiguous and non-overlapping")
        previous_upper = row.upper_bound_cents
    if open_ended != 1 or sorted_rows[-1].upper_bound_cents is not None:
        errors.append("exactly one open-ended top bracket is required")
    return BracketValidationResult(valid=not errors, errors=errors)
