"""Charitable-giving planning engine — bunching (DAF) and QCD benefit.

Two deterministic levers a tax-planning advisor reaches for whenever a client
gives to charity:

  * **Bunching** — concentrating several years of gifts into one year (often
    through a donor-advised fund) so the itemized total clears the standard
    deduction in the bunch year, while the off years still take the standard
    deduction. The benefit is the *extra* deduction the bunch buys over giving
    the same dollars annually, valued at the client's marginal rate.

  * **QCD** — a Qualified Charitable Distribution sends IRA dollars straight to
    charity, excluding them from AGI. For a donor who would otherwise take the
    standard deduction (so the gift produces no itemized benefit), the QCD makes
    the gift effectively deductible AND lowers AGI (helping IRMAA, the SS
    taxability bases, NIIT, etc.).

Every figure is integer cents; the model rounds tax to whole dollars. The 2026
constants (standard deductions, the $111,000 QCD limit, and the new 0.5%-of-AGI
floor on itemized charitable deductions) are research- and adversarially-
verified against Rev. Proc. 2025-32 + OBBBA.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

FilingStatus = str


def _dollars(value: Decimal) -> int:
    return int((value / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


class CharitableConfig(BaseModel):
    tax_year: int
    # Per-person annual QCD ceiling (IRC §408(d)(8), indexed).
    qcd_annual_limit_cents: int
    # OBBBA §70425: the first 0.5% of AGI in itemized charitable gifts is
    # nondeductible, effective 2026. 0 before 2026.
    charitable_agi_floor_rate: Decimal = Decimal("0")
    # Cash-to-public-charity AGI ceiling (IRC §170(b)(1)(A)); informational here.
    cash_agi_limit_rate: Decimal = Decimal("0.60")


def ty2025_charitable_config() -> CharitableConfig:
    return CharitableConfig(
        tax_year=2025,
        qcd_annual_limit_cents=10_800_000,  # $108,000 (2025)
        charitable_agi_floor_rate=Decimal("0"),  # floor starts 2026
    )


def ty2026_charitable_config() -> CharitableConfig:
    return CharitableConfig(
        tax_year=2026,
        qcd_annual_limit_cents=11_100_000,  # $111,000 (2026, indexed)
        charitable_agi_floor_rate=Decimal("0.005"),  # OBBBA 0.5%-of-AGI floor
    )


# ---------------------------------------------------------------------------
# Bunching (donor-advised fund) benefit
# ---------------------------------------------------------------------------


class BunchingInput(BaseModel):
    annual_giving_cents: int  # what the client gives in a typical year
    years_bunched: int = Field(default=3, ge=2)  # years pulled into the bunch year
    standard_deduction_cents: int  # the client's actual standard deduction
    other_itemized_cents: int = 0  # SALT, mortgage interest, etc. (recurring)
    marginal_rate: Decimal
    agi_cents: int = 0  # only needed when a charitable AGI floor applies


class BunchingResult(BaseModel):
    years_bunched: int
    bunched_giving_cents: int
    charitable_floor_cents: int
    extra_deduction_cents: int  # deduction the bunch buys over annual giving
    tax_savings_cents: int  # extra_deduction × marginal, over the window
    annual_itemizes: bool  # would annual giving already itemize?
    bunch_year_itemizes: bool


def _deductible_charitable(gift_cents: int, floor_cents: int) -> int:
    return max(0, gift_cents - floor_cents)


def _calculate_bunching(
    inputs: BunchingInput, *, charitable_floor_rate: Decimal = Decimal("0"),
) -> BunchingResult:
    n = inputs.years_bunched
    floor_cents = _dollars(Decimal(max(inputs.agi_cents, 0)) * charitable_floor_rate)

    # Giving annually: each year itemize only if other + (gift−floor) > std.
    annual_gift_ded = _deductible_charitable(inputs.annual_giving_cents, floor_cents)
    annual_itemized = inputs.other_itemized_cents + annual_gift_ded
    annual_benefit_year = max(0, annual_itemized - inputs.standard_deduction_cents)
    total_annual = annual_benefit_year * n

    # Bunching N years into one: bunch year itemizes a big gift; off years take
    # the standard deduction (unless their recurring itemized already exceeds it).
    bunched_giving = inputs.annual_giving_cents * n
    bunch_gift_ded = _deductible_charitable(bunched_giving, floor_cents)
    bunch_itemized = inputs.other_itemized_cents + bunch_gift_ded
    bunch_benefit_year = max(0, bunch_itemized - inputs.standard_deduction_cents)
    off_year_benefit = max(0, inputs.other_itemized_cents - inputs.standard_deduction_cents)
    total_bunch = bunch_benefit_year + off_year_benefit * (n - 1)

    extra_deduction = max(0, total_bunch - total_annual)
    tax_savings = _dollars(Decimal(extra_deduction) * inputs.marginal_rate)
    return BunchingResult(
        years_bunched=n,
        bunched_giving_cents=bunched_giving,
        charitable_floor_cents=floor_cents,
        extra_deduction_cents=extra_deduction,
        tax_savings_cents=tax_savings,
        annual_itemizes=annual_itemized > inputs.standard_deduction_cents,
        bunch_year_itemizes=bunch_itemized > inputs.standard_deduction_cents,
    )


def bunching_benefit(inputs: BunchingInput, config: CharitableConfig) -> BunchingResult:
    """Tax saved by bunching `years_bunched` years of gifts into one, valued at
    the marginal rate, net of the standard deduction the off years still take and
    the charitable AGI floor (2026+)."""
    return _calculate_bunching(inputs, charitable_floor_rate=config.charitable_agi_floor_rate)


# ---------------------------------------------------------------------------
# Qualified Charitable Distribution (QCD) benefit
# ---------------------------------------------------------------------------


class QCDInput(BaseModel):
    intended_giving_cents: int  # how much the client wants to give
    ira_distribution_available_cents: int  # IRA dollars that could be routed
    marginal_rate: Decimal
    takes_standard_deduction: bool  # if True, an ordinary gift gives no benefit


class QCDResult(BaseModel):
    qcd_amount_cents: int  # routable from the IRA, capped at the annual limit
    agi_reduction_cents: int  # income excluded from AGI
    tax_savings_cents: int  # marginal benefit vs an ordinary (often nondeductible) gift
    capped_by_limit: bool
    note: str


def qcd_benefit(inputs: QCDInput, config: CharitableConfig) -> QCDResult:
    routable = min(
        max(inputs.intended_giving_cents, 0),
        max(inputs.ira_distribution_available_cents, 0),
    )
    qcd = min(routable, config.qcd_annual_limit_cents)
    capped = routable > config.qcd_annual_limit_cents
    # A QCD excludes the gift from AGI. For a standard-deduction donor the gift
    # was producing no itemized benefit, so the whole exclusion is new tax saved.
    # An itemizer already deducts the gift; the QCD's edge is the AGI reduction
    # (IRMAA/SS/NIIT thresholds) — surfaced as the note, modeled conservatively
    # at zero direct income-tax savings.
    tax_savings = (
        _dollars(Decimal(qcd) * inputs.marginal_rate)
        if inputs.takes_standard_deduction
        else 0
    )
    note = (
        "QCD makes the gift effectively deductible for a standard-deduction donor "
        "and lowers AGI. Requires age 70½+ and a direct IRA-to-charity transfer."
        if inputs.takes_standard_deduction
        else "Itemizer: the QCD's benefit is the AGI reduction (IRMAA/SS/NIIT), "
        "not a second deduction. Requires age 70½+ and a direct transfer."
    )
    return QCDResult(
        qcd_amount_cents=qcd,
        agi_reduction_cents=qcd,
        tax_savings_cents=tax_savings,
        capped_by_limit=capped,
        note=note,
    )


def charitable_config_for(year: int) -> CharitableConfig:
    return ty2026_charitable_config() if year >= 2026 else ty2025_charitable_config()
