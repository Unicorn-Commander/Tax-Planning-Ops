"""Alternative Minimum Tax — Form 6251, tax year 2025.

Planning-grade AMT: build AMTI from regular taxable income plus the high-value
preference add-backs an advisor cares about (standard deduction if used, the
SALT itemized deduction, and a catch-all preferences field for ISO bargain
element etc.), apply the 2025 exemption with its 25% phaseout, tax the ordinary
excess at 26%/28%, retain preferential rates on capital gains/qualified
dividends (Form 6251 Part III), and return AMT = max(0, TMT − regular tax).

LTCG brackets are passed in (the same ones the federal engine uses) so this
engine introduces no capital-gain-rate constants of its own. All money is cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.engines.form1040 import RateBracket, _preferential_tax

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class AMTBracketParams(BaseModel):
    exemption_cents: int
    phaseout_threshold_cents: int
    rate_breakpoint_cents: int  # 26% below, 28% above
    breakpoint_subtraction_cents: int  # = 0.02 × rate_breakpoint (continuity term)


class AMTConfig(BaseModel):
    tax_year: int
    params: dict[str, AMTBracketParams]
    phaseout_rate: Decimal = Decimal("0.25")
    lower_rate: Decimal = Decimal("0.26")
    upper_rate: Decimal = Decimal("0.28")


def ty2025_amt_config() -> AMTConfig:
    single = AMTBracketParams(
        exemption_cents=8_810_000,  # $88,100
        phaseout_threshold_cents=62_635_000,  # $626,350
        rate_breakpoint_cents=23_910_000,  # $239,100
        breakpoint_subtraction_cents=478_200,  # $4,782
    )
    mfj = AMTBracketParams(
        exemption_cents=13_700_000,  # $137,000
        phaseout_threshold_cents=125_270_000,  # $1,252,700
        rate_breakpoint_cents=23_910_000,
        breakpoint_subtraction_cents=478_200,
    )
    mfs = AMTBracketParams(
        exemption_cents=6_850_000,  # $68,500
        phaseout_threshold_cents=62_635_000,  # $626,350 (half of MFJ)
        rate_breakpoint_cents=11_955_000,  # $119,550
        breakpoint_subtraction_cents=239_100,  # $2,391
    )
    return AMTConfig(
        tax_year=2025,
        params={"single": single, "hoh": single, "qss": mfj, "mfj": mfj, "mfs": mfs},
    )


class AMTInput(BaseModel):
    filing_status: FilingStatus
    regular_taxable_income_cents: int
    regular_tax_for_amt_cents: int  # regular tax used in the TMT comparison
    used_standard_deduction: bool = False
    standard_deduction_cents: int = 0
    salt_addback_cents: int = 0
    other_preferences_cents: int = 0  # ISO bargain element, private-activity bond interest, …
    amt_preferential_income_cents: int = 0  # qualified div + net LTCG inside AMTI
    ltcg_brackets: list[RateBracket] = Field(default_factory=list)


class AMTResult(BaseModel):
    amti_cents: int
    exemption_cents: int
    taxable_excess_cents: int
    tentative_minimum_tax_cents: int
    regular_tax_for_amt_cents: int
    amt_cents: int  # the additional tax owed (line 11)
    amt_applies: bool
    assumptions: list[str] = Field(default_factory=list)


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_amt(inputs: AMTInput, config: AMTConfig) -> AMTResult:
    params = config.params.get(inputs.filing_status)
    if params is None:
        raise ValueError(f"no AMT params configured for {inputs.filing_status}")

    addbacks = inputs.salt_addback_cents + inputs.other_preferences_cents
    if inputs.used_standard_deduction:
        addbacks += inputs.standard_deduction_cents
    amti = max(inputs.regular_taxable_income_cents + addbacks, 0)

    # Exemption with 25% phaseout over the threshold.
    phaseout = _cents(
        Decimal(max(amti - params.phaseout_threshold_cents, 0)) * config.phaseout_rate
    )
    exemption = max(params.exemption_cents - phaseout, 0)

    taxable_excess = max(amti - exemption, 0)

    # Split the excess: preferential income keeps capital-gain rates (Part III);
    # the ordinary remainder is taxed at 26%/28%.
    pref_used = max(min(inputs.amt_preferential_income_cents, taxable_excess), 0)
    ordinary_base = taxable_excess - pref_used

    if ordinary_base <= params.rate_breakpoint_cents:
        amt_ordinary_tax = _cents(Decimal(ordinary_base) * config.lower_rate)
    else:
        amt_ordinary_tax = _cents(
            Decimal(ordinary_base) * config.upper_rate
        ) - params.breakpoint_subtraction_cents

    pref_tax = 0
    if pref_used > 0 and inputs.ltcg_brackets:
        pref_tax = _preferential_tax(
            taxable_excess,  # total AMT-taxed amount
            ordinary_base,  # ordinary stack base
            pref_used,
            inputs.ltcg_brackets,
        )

    tmt = amt_ordinary_tax + pref_tax
    amt = max(tmt - max(inputs.regular_tax_for_amt_cents, 0), 0)

    assumptions: list[str] = []
    if pref_used > 0 and not inputs.ltcg_brackets:
        assumptions.append(
            "amt_preferential_income_taxed_as_ordinary: no LTCG brackets supplied, so "
            "capital-gain/qualified-dividend income inside AMTI was taxed at 26%/28% "
            "(overstates AMT). Supply ltcg_brackets to retain preferential rates."
        )

    return AMTResult(
        amti_cents=amti,
        exemption_cents=exemption,
        taxable_excess_cents=taxable_excess,
        tentative_minimum_tax_cents=tmt,
        regular_tax_for_amt_cents=max(inputs.regular_tax_for_amt_cents, 0),
        amt_cents=amt,
        amt_applies=amt > 0,
        assumptions=assumptions,
    )
