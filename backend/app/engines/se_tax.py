"""Self-Employment tax — Schedule SE, tax year 2025.

Net SE earnings = 92.35% of net Schedule C profit. The 12.4% OASDI portion
applies to net SE earnings up to the Social Security wage base ($176,100 for
2025), reduced by any W-2 Social Security wages already taxed; the 2.9% Medicare
portion is UNCAPPED on the full net earnings (and is NOT reduced by W-2 wages —
the key coordination rule). The above-the-line deduction is 50% of the SE tax.

Scope note: the 0.9% Additional Medicare Tax (Form 8959) is handled in the
federal engine on wages; optional methods and church-employee income are out of
scope. All money is integer cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel


class SETaxConfig(BaseModel):
    tax_year: int
    net_earnings_factor: Decimal
    ss_wage_base_cents: int  # Social Security wage base
    oasdi_rate: Decimal
    medicare_rate: Decimal
    half_deduction_rate: Decimal
    filing_floor_cents: int  # no SE tax below this in net earnings


class SETaxInput(BaseModel):
    net_self_employment_profit_cents: int  # net Schedule C / K-1 SE earnings
    w2_social_security_wages_cents: int = 0  # already-taxed W-2 SS wages this year


class SETaxResult(BaseModel):
    net_se_earnings_cents: int
    oasdi_taxable_base_cents: int
    oasdi_cents: int
    medicare_cents: int
    total_se_tax_cents: int
    half_se_deduction_cents: int


def _cents(value: Decimal) -> int:
    # Schedule SE rounds each line to whole dollars.
    return int((value / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def calculate_se_tax(inputs: SETaxInput, config: SETaxConfig) -> SETaxResult:
    net_se = _cents(
        Decimal(max(inputs.net_self_employment_profit_cents, 0)) * config.net_earnings_factor
    )
    if net_se < config.filing_floor_cents:
        return SETaxResult(
            net_se_earnings_cents=net_se,
            oasdi_taxable_base_cents=0,
            oasdi_cents=0,
            medicare_cents=0,
            total_se_tax_cents=0,
            half_se_deduction_cents=0,
        )

    w2_ss = max(inputs.w2_social_security_wages_cents, 0)
    remaining_base = max(config.ss_wage_base_cents - w2_ss, 0)
    oasdi_base = min(net_se, remaining_base)
    oasdi = _cents(Decimal(oasdi_base) * config.oasdi_rate)
    medicare = _cents(Decimal(net_se) * config.medicare_rate)  # uncapped, full net
    total = oasdi + medicare
    half = _cents(Decimal(total) * config.half_deduction_rate)
    return SETaxResult(
        net_se_earnings_cents=net_se,
        oasdi_taxable_base_cents=oasdi_base,
        oasdi_cents=oasdi,
        medicare_cents=medicare,
        total_se_tax_cents=total,
        half_se_deduction_cents=half,
    )
