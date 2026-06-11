"""Taxable portion of Social Security benefits — IRC §86 / Pub 915 Worksheet.

Replaces taking `social_security_taxable_cents` as a raw input: given the gross
benefits and the rest of the picture, compute how much is actually taxable
(0%, up to 50%, or up to 85%). The base amounts are statutory and NOT
inflation-indexed, so the 2025 config is the long-standing fixed table.

Note: OBBBA (P.L. 119-21) did not touch the §86 worksheet; its separate $6,000
senior deduction is a downstream below-the-line item and is intentionally not
modeled here.

All money is integer cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss", "mfs_lived_with_spouse"]

_HALF = Decimal("0.5")
_EIGHTYFIVE = Decimal("0.85")


class SSBaseAmounts(BaseModel):
    base1_cents: int  # first threshold (50% tier begins)
    base2_cents: int  # second threshold (85% tier begins)


class SSConfig(BaseModel):
    tax_year: int
    bases: dict[str, SSBaseAmounts]
    tier1_rate: Decimal = _HALF
    tier2_rate: Decimal = _EIGHTYFIVE


def ty2025_ss_config() -> SSConfig:
    """2025 statutory base amounts (unchanged since 1993 — not indexed)."""
    single = SSBaseAmounts(base1_cents=2_500_000, base2_cents=3_400_000)
    mfj = SSBaseAmounts(base1_cents=3_200_000, base2_cents=4_400_000)
    # MFS while living with spouse at any time in the year: bases are $0, so up
    # to 85% is taxable from the first dollar of provisional income.
    mfs_together = SSBaseAmounts(base1_cents=0, base2_cents=0)
    return SSConfig(
        tax_year=2025,
        bases={
            "single": single,
            "hoh": single,
            "qss": single,
            "mfs": single,  # MFS living APART uses the single bases
            "mfj": mfj,
            "mfs_lived_with_spouse": mfs_together,
        },
    )


class SSInput(BaseModel):
    filing_status: FilingStatus
    social_security_benefits_cents: int = 0
    # All other income that lands in AGI EXCLUDING the taxable SS portion
    # (wages, interest, dividends, cap gains, IRA/pension, Sch-1 income) net of
    # the adjustments that the worksheet allows. Provide it pre-netted.
    other_income_cents: int = 0
    tax_exempt_interest_cents: int = 0


class SSResult(BaseModel):
    provisional_income_cents: int
    taxable_social_security_cents: int
    taxable_percentage: Decimal  # taxable / benefits (0, .5-ish, up to .85)
    tier: Literal["none", "fifty", "eighty_five"]
    assumptions: list[str] = Field(default_factory=list)


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_taxable_ss(inputs: SSInput, config: SSConfig) -> SSResult:
    bases = config.bases.get(inputs.filing_status)
    if bases is None:
        raise ValueError(f"no SS base amounts configured for {inputs.filing_status}")
    benefits = max(inputs.social_security_benefits_cents, 0)
    if benefits == 0:
        return SSResult(
            provisional_income_cents=0,
            taxable_social_security_cents=0,
            taxable_percentage=Decimal("0"),
            tier="none",
        )

    half_benefits = _cents(Decimal(benefits) * config.tier1_rate)
    provisional = max(inputs.other_income_cents, 0) + max(
        inputs.tax_exempt_interest_cents, 0
    ) + half_benefits

    if provisional <= bases.base1_cents:
        return SSResult(
            provisional_income_cents=provisional,
            taxable_social_security_cents=0,
            taxable_percentage=Decimal("0"),
            tier="none",
        )

    over_base1 = provisional - bases.base1_cents
    if provisional <= bases.base2_cents:
        taxable = min(half_benefits, _cents(Decimal(over_base1) * config.tier1_rate))
        tier: Literal["fifty", "eighty_five"] = "fifty"
    else:
        over_base2 = provisional - bases.base2_cents
        # the lesser of half the benefits or half the gap between the bases
        gap_amount = min(
            half_benefits,
            _cents(Decimal(bases.base2_cents - bases.base1_cents) * config.tier1_rate),
        )
        taxable = min(
            _cents(Decimal(benefits) * config.tier2_rate),
            _cents(Decimal(over_base2) * config.tier2_rate) + gap_amount,
        )
        tier = "eighty_five"

    taxable = max(0, min(taxable, _cents(Decimal(benefits) * config.tier2_rate)))
    pct = Decimal(taxable) / Decimal(benefits)
    return SSResult(
        provisional_income_cents=provisional,
        taxable_social_security_cents=taxable,
        taxable_percentage=pct,
        tier=tier,
    )
