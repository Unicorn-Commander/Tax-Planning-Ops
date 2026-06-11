"""Comprehensive return orchestrator — composes the federal engine with the
Social Security taxability, Child Tax Credit, and AMT engines into one result.

Order of operations mirrors the 1040 itself:
  1. compute the taxable portion of any gross Social Security benefits and feed
     it into total income;
  2. compute the regular tax once to get the credit-limiting liability, compute
     the CTC/ODC nonrefundable amount, then recompute the regular return with
     that credit applied (the refundable ACTC is tracked separately);
  3. compute AMT off the final regular return and add the excess;
  4. total tax = regular total + AMT; balance due nets payments and the
     refundable ACTC.

Each sub-engine is independently golden-tested; this module is verified to
compose them correctly. Pure function, integer cents.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engines.amt import AMTConfig, AMTInput, AMTResult, calculate_amt
from app.engines.ctc import CTCConfig, CTCInput, CTCResult, calculate_ctc
from app.engines.form1040 import Form1040Inputs, Form1040Result, TaxConfig, calculate_form1040
from app.engines.ss_taxability import SSConfig, SSInput, SSResult, calculate_taxable_ss


class ComprehensiveInput(BaseModel):
    form1040: Form1040Inputs
    # If > 0, the taxable portion is computed and overrides
    # form1040.social_security_taxable_cents.
    social_security_benefits_gross_cents: int = 0
    tax_exempt_interest_cents: int = 0
    qualifying_children: int = 0
    other_dependents: int = 0
    earned_income_cents: int | None = None  # defaults to wages
    salt_deduction_cents: int = 0  # AMT add-back
    amt_other_preferences_cents: int = 0  # ISO bargain element, PAB interest, …
    used_standard_deduction: bool | None = None  # default: standard >= itemized


class ComprehensiveResult(BaseModel):
    federal: Form1040Result
    social_security: SSResult | None
    ctc: CTCResult | None
    amt: AMTResult | None
    regular_total_tax_cents: int
    amt_cents: int
    refundable_credits_cents: int
    total_tax_cents: int
    balance_due_cents: int
    assumptions: list[str] = Field(default_factory=list)


def _other_income_excluding_ss(inputs: Form1040Inputs) -> int:
    return (
        inputs.wages_cents
        + inputs.taxable_interest_cents
        + inputs.ordinary_dividends_cents
        + inputs.ira_taxable_cents
        + inputs.pensions_taxable_cents
        + inputs.capital_gain_loss_cents
        + inputs.schedule_1_income_cents
        - inputs.adjustments_cents
    )


def calculate_comprehensive(
    payload: ComprehensiveInput,
    config: TaxConfig,
    *,
    ss_config: SSConfig | None = None,
    ctc_config: CTCConfig | None = None,
    amt_config: AMTConfig | None = None,
) -> ComprehensiveResult:
    assumptions: list[str] = []
    base_inputs = payload.form1040

    # 1. Social Security taxability.
    ss_result: SSResult | None = None
    if payload.social_security_benefits_gross_cents > 0 and ss_config is not None:
        ss_result = calculate_taxable_ss(
            SSInput(
                filing_status=base_inputs.filing_status,
                social_security_benefits_cents=payload.social_security_benefits_gross_cents,
                other_income_cents=_other_income_excluding_ss(base_inputs),
                tax_exempt_interest_cents=payload.tax_exempt_interest_cents,
            ),
            ss_config,
        )
        base_inputs = base_inputs.model_copy(
            update={"social_security_taxable_cents": ss_result.taxable_social_security_cents}
        )
        assumptions.append(
            f"social_security_taxable computed at {ss_result.taxable_percentage:.0%} of "
            f"gross benefits ({ss_result.tier} tier)."
        )

    other_credits = max(base_inputs.nonrefundable_credits_cents, 0)

    # 2. CTC: first pass for the credit-limiting tax, then recompute with the credit.
    ctc_result: CTCResult | None = None
    final = calculate_form1040(base_inputs, config)
    if (payload.qualifying_children or payload.other_dependents) and ctc_config is not None:
        income_tax = final.ordinary_tax_cents + final.preferential_tax_cents
        ctc_limit = max(income_tax - other_credits, 0)
        ctc_result = calculate_ctc(
            CTCInput(
                filing_status=base_inputs.filing_status,
                qualifying_children=payload.qualifying_children,
                other_dependents=payload.other_dependents,
                magi_cents=final.agi_cents,
                tax_liability_cents=ctc_limit,
                earned_income_cents=(
                    payload.earned_income_cents
                    if payload.earned_income_cents is not None
                    else base_inputs.wages_cents
                ),
            ),
            ctc_config,
        )
        assumptions.extend(ctc_result.assumptions)
        base_inputs = base_inputs.model_copy(
            update={
                "nonrefundable_credits_cents": other_credits
                + ctc_result.nonrefundable_ctc_odc_cents
            }
        )
        final = calculate_form1040(base_inputs, config)

    refundable = ctc_result.refundable_actc_cents if ctc_result else 0

    # 3. AMT off the final regular return.
    amt_result: AMTResult | None = None
    amt_cents = 0
    if amt_config is not None:
        used_standard = (
            payload.used_standard_deduction
            if payload.used_standard_deduction is not None
            else config.standard_deduction_cents >= base_inputs.itemized_deduction_cents
        )
        regular_tax_for_amt = (
            final.ordinary_tax_cents
            + final.preferential_tax_cents
            - final.nonrefundable_credits_cents
        )
        amt_preferential = max(base_inputs.qualified_dividends_cents, 0) + max(
            base_inputs.capital_gain_loss_cents, 0
        )
        amt_result = calculate_amt(
            AMTInput(
                filing_status=base_inputs.filing_status,
                regular_taxable_income_cents=final.taxable_income_cents,
                regular_tax_for_amt_cents=max(regular_tax_for_amt, 0),
                used_standard_deduction=used_standard,
                standard_deduction_cents=config.standard_deduction_cents,
                salt_addback_cents=payload.salt_deduction_cents,
                other_preferences_cents=payload.amt_other_preferences_cents,
                amt_preferential_income_cents=amt_preferential,
                ltcg_brackets=config.auxiliary.ltcg_brackets,
            ),
            amt_config,
        )
        amt_cents = amt_result.amt_cents
        assumptions.extend(amt_result.assumptions)

    total_tax = final.total_tax_cents + amt_cents
    payments = base_inputs.withholding_cents + base_inputs.estimated_payments_cents
    balance_due = total_tax - payments - refundable

    assumptions.extend(final.assumptions)
    return ComprehensiveResult(
        federal=final,
        social_security=ss_result,
        ctc=ctc_result,
        amt=amt_result,
        regular_total_tax_cents=final.total_tax_cents,
        amt_cents=amt_cents,
        refundable_credits_cents=refundable,
        total_tax_cents=total_tax,
        balance_due_cents=balance_due,
        assumptions=assumptions,
    )
