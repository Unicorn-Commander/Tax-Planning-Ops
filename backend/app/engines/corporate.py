"""C-corporation tax — Form 1120 + §1202 QSBS + Accumulated Earnings Tax.

A C-corp pays its OWN tax (flat 21% on corporate taxable income, which is after
deducting the owner's reasonable salary); the owner is taxed AGAIN on salary (as
1040 wages) and on distributions (as qualified dividends) — the double tax.
C-corp income does NOT pass through and is NOT QBI. Magic Unicorn is a C-corp.

This module computes the corporate-level tax (with the §172 NOL 80% limit), the
§1202 qualified-small-business-stock gain exclusion (post-OBBBA tiered rules),
and Accumulated Earnings Tax exposure. The owner-level salary/dividend pieces
flow through the existing 1040 engine. All money is integer cents; 2025 config
lives in app/engine_configs.py.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel


class CorporateConfig(BaseModel):
    tax_year: int
    corporate_rate: Decimal  # flat federal corporate rate (21%)
    nol_limit_pct: Decimal  # §172: NOL deduction ≤ this × pre-NOL taxable income
    qsbs_rate: Decimal  # 28% rate on the taxable (non-excluded) §1202 gain
    qsbs_cap_new_cents: int  # $15M per-issuer cap (stock acquired after 7/4/2025)
    qsbs_cap_old_cents: int  # $10M per-issuer cap (older stock)
    qsbs_assets_ceiling_new_cents: int  # $75M aggregate-gross-assets ceiling (new)
    qsbs_assets_ceiling_old_cents: int  # $50M (old)
    aet_rate: Decimal  # 20% accumulated earnings tax
    aet_credit_cents: int  # $250,000 accumulated-earnings credit
    aet_credit_psc_cents: int  # $150,000 for personal service corporations


# ---------------------------------------------------------------------------
# Corporate income tax (Form 1120) with the §172 NOL limit
# ---------------------------------------------------------------------------


class CorporateTaxInput(BaseModel):
    pre_nol_taxable_income_cents: int  # corporate taxable income before any NOL
    nol_available_cents: int = 0  # NOL carryforward available


class CorporateTaxResult(BaseModel):
    corporate_taxable_income_cents: int  # after the NOL deduction
    nol_deduction_cents: int
    nol_carryforward_remaining_cents: int
    corporate_tax_cents: int


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# State corporate income tax (flat-rate states; layered on top of federal 1120)
# ---------------------------------------------------------------------------


class StateCorporateConfig(BaseModel):
    state: str
    tax_year: int
    corporate_rate: Decimal  # flat state corporate income-tax rate on state taxable income


class StateCorporateResult(BaseModel):
    state: str
    state_taxable_income_cents: int
    state_corporate_tax_cents: int
    marginal_rate: Decimal


def calculate_state_corporate_tax(
    state_taxable_income_cents: int, config: StateCorporateConfig
) -> StateCorporateResult:
    """Flat-rate state C-corp tax. State corporate taxable income is its own
    apportioned figure (SC starts from federal taxable income with modifications
    and single-sales-factor apportionment); the caller supplies it. SC's annual
    license fee (0.1% of capital + paid-in surplus, $25 min) is a SEPARATE levy,
    not an income tax, and is not computed here.
    """
    taxable = max(state_taxable_income_cents, 0)
    tax = _cents(Decimal(taxable) * config.corporate_rate)
    return StateCorporateResult(
        state=config.state, state_taxable_income_cents=taxable,
        state_corporate_tax_cents=tax, marginal_rate=config.corporate_rate,
    )


def calculate_corporate_tax(
    inputs: CorporateTaxInput, config: CorporateConfig
) -> CorporateTaxResult:
    pre_nol = max(inputs.pre_nol_taxable_income_cents, 0)
    nol_cap = _cents(Decimal(pre_nol) * config.nol_limit_pct)
    nol_deduction = min(max(inputs.nol_available_cents, 0), nol_cap)
    taxable = pre_nol - nol_deduction
    corporate_tax = _cents(Decimal(taxable) * config.corporate_rate)
    return CorporateTaxResult(
        corporate_taxable_income_cents=taxable,
        nol_deduction_cents=nol_deduction,
        nol_carryforward_remaining_cents=max(inputs.nol_available_cents, 0) - nol_deduction,
        corporate_tax_cents=corporate_tax,
    )


# ---------------------------------------------------------------------------
# §1202 Qualified Small Business Stock gain exclusion (post-OBBBA)
# ---------------------------------------------------------------------------


class QSBSInput(BaseModel):
    eligible_gain_cents: int  # gain on the QSBS sale
    basis_cents: int  # stock basis (for the 10× cap)
    holding_years: int  # full years held
    acquired_after_obbba: bool  # acquired after 2025-07-04 → new tiered regime
    is_psc: bool = False  # unused here; kept for symmetry


class QSBSResult(BaseModel):
    qualified: bool
    exclusion_pct: Decimal
    per_issuer_cap_cents: int
    excluded_gain_cents: int
    taxable_gain_cents: int
    tax_on_taxable_gain_cents: int  # at the §1202 28% rate
    amt_preference_cents: int  # 0 for the new tiers (statutory reading — disputed)
    notes: list[str]


def calculate_qsbs(inputs: QSBSInput, config: CorporateConfig) -> QSBSResult:
    notes: list[str] = []
    # Holding-period exclusion %.
    if inputs.acquired_after_obbba:
        if inputs.holding_years >= 5:
            pct = Decimal("1.00")
        elif inputs.holding_years >= 4:
            pct = Decimal("0.75")
        elif inputs.holding_years >= 3:
            pct = Decimal("0.50")
        else:
            pct = Decimal("0")
        cap = config.qsbs_cap_new_cents
    else:
        pct = Decimal("1.00") if inputs.holding_years >= 5 else Decimal("0")
        cap = config.qsbs_cap_old_cents

    if pct == 0:
        return QSBSResult(
            qualified=False, exclusion_pct=Decimal("0"),
            per_issuer_cap_cents=cap, excluded_gain_cents=0,
            taxable_gain_cents=max(inputs.eligible_gain_cents, 0),
            tax_on_taxable_gain_cents=_cents(
                Decimal(max(inputs.eligible_gain_cents, 0)) * config.qsbs_rate
            ),
            amt_preference_cents=0,
            notes=["Holding period too short for any §1202 exclusion."],
        )

    # Per-issuer cap = greater of the dollar cap or 10× basis.
    per_issuer_cap = max(cap, inputs.basis_cents * 10)
    eligible = max(inputs.eligible_gain_cents, 0)
    excludable = min(eligible, per_issuer_cap)
    excluded = _cents(Decimal(excludable) * pct)
    taxable_gain = eligible - excluded
    tax = _cents(Decimal(taxable_gain) * config.qsbs_rate)

    # §57(a)(7) AMT preference applies only to pre-9/28/2010 stock; for the new
    # OBBBA tiers the statute as written adds no preference. Practitioner sources
    # split and there is no Treasury guidance — modeled as 0, flagged.
    if pct < 1:
        notes.append(
            "AMT preference on the excluded gain is unsettled for the new tiers "
            "(§57(a)(7) as written applies only to pre-9/28/2010 stock); modeled as 0."
        )
    return QSBSResult(
        qualified=True, exclusion_pct=pct, per_issuer_cap_cents=per_issuer_cap,
        excluded_gain_cents=excluded, taxable_gain_cents=taxable_gain,
        tax_on_taxable_gain_cents=tax, amt_preference_cents=0, notes=notes,
    )


# ---------------------------------------------------------------------------
# Accumulated Earnings Tax (§531/§535)
# ---------------------------------------------------------------------------


class AETInput(BaseModel):
    accumulated_taxable_income_cents: int
    prior_year_accumulated_ep_cents: int = 0
    is_psc: bool = False


class AETResult(BaseModel):
    credit_cents: int
    accumulated_taxable_income_over_credit_cents: int
    estimated_aet_cents: int
    exposed: bool


def calculate_aet(inputs: AETInput, config: CorporateConfig) -> AETResult:
    base_credit = config.aet_credit_psc_cents if inputs.is_psc else config.aet_credit_cents
    # §535(c)(2): the minimum credit is reduced by prior-year accumulated E&P.
    credit = max(base_credit - max(inputs.prior_year_accumulated_ep_cents, 0), 0)
    over = max(inputs.accumulated_taxable_income_cents - credit, 0)
    aet = _cents(Decimal(over) * config.aet_rate)
    return AETResult(
        credit_cents=credit,
        accumulated_taxable_income_over_credit_cents=over,
        estimated_aet_cents=aet,
        exposed=aet > 0,
    )
