"""§199A Qualified Business Income deduction — full rules, tax year 2025.

Implements the three regimes for a single trade/business:
  * below the taxable-income threshold → simple 20% of QBI (no wage limit, no
    SSTB haircut);
  * above the upper threshold → the W-2-wage/UBIA limit binds (and an SSTB is
    fully disallowed);
  * inside the phase-in range → the SSTB applicable-percentage reduction is
    applied to QBI/W-2/UBIA FIRST, then the wage-limit reduction is phased in by
    the same fraction (Reg. §1.199A-1(d)(2)(iv) / §1.199A-5(d)(1)).
The result is capped at 20% of (taxable income − net capital gain).

2025 thresholds from Rev. Proc. 2024-40 (MFS uses the single threshold, NOT
half). This is the TY2025 form; the post-2025 OBBBA widened phase-in ranges are
intentionally not applied. All money is integer cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class QBIThreshold(BaseModel):
    threshold_cents: int
    phase_in_width_cents: int


class QBIConfig(BaseModel):
    tax_year: int
    thresholds: dict[str, QBIThreshold]
    qbi_rate: Decimal = Decimal("0.20")
    wage_rate: Decimal = Decimal("0.50")
    wage_ubia_wage_rate: Decimal = Decimal("0.25")
    ubia_rate: Decimal = Decimal("0.025")


class QBIInput(BaseModel):
    filing_status: FilingStatus
    qualified_business_income_cents: int
    w2_wages_cents: int = 0
    ubia_cents: int = 0  # unadjusted basis immediately after acquisition of qualified property
    taxable_income_before_qbi_cents: int = 0
    net_capital_gain_cents: int = 0  # qualified dividends + net LTCG
    is_sstb: bool = False


class QBIResult(BaseModel):
    regime: Literal["below", "phase_in", "full"]
    phase_in_fraction: Decimal
    tentative_deduction_cents: int  # 20% of full QBI (pre-limits)
    wage_limit_cents: int
    qbi_component_cents: int
    overall_cap_cents: int
    allowed_qbi_deduction_cents: int


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _wage_limit(w2: int, ubia: int, config: QBIConfig) -> int:
    return max(
        _cents(Decimal(w2) * config.wage_rate),
        _cents(Decimal(w2) * config.wage_ubia_wage_rate + Decimal(ubia) * config.ubia_rate),
    )


def calculate_qbi(inputs: QBIInput, config: QBIConfig) -> QBIResult:
    params = config.thresholds.get(inputs.filing_status)
    if params is None:
        raise ValueError(f"no QBI threshold configured for {inputs.filing_status}")

    qbi = max(inputs.qualified_business_income_cents, 0)
    ti = inputs.taxable_income_before_qbi_cents
    tentative_full = _cents(Decimal(qbi) * config.qbi_rate)
    overall_cap = max(
        _cents(Decimal(max(ti - inputs.net_capital_gain_cents, 0)) * config.qbi_rate), 0
    )

    upper = params.threshold_cents + params.phase_in_width_cents

    if ti <= params.threshold_cents:
        regime: Literal["below", "phase_in", "full"] = "below"
        fraction = Decimal("0")
        qbi_component = tentative_full
        wage_limit = 0
    elif ti >= upper:
        regime = "full"
        fraction = Decimal("1")
        if inputs.is_sstb:
            wage_limit = 0
            qbi_component = 0
        else:
            wage_limit = _wage_limit(inputs.w2_wages_cents, inputs.ubia_cents, config)
            qbi_component = min(tentative_full, wage_limit)
    else:
        regime = "phase_in"
        fraction = Decimal(ti - params.threshold_cents) / Decimal(params.phase_in_width_cents)
        applicable = Decimal("1") - fraction if inputs.is_sstb else Decimal("1")
        qbi_a = _cents(Decimal(qbi) * applicable)
        w2_a = _cents(Decimal(inputs.w2_wages_cents) * applicable)
        ubia_a = _cents(Decimal(inputs.ubia_cents) * applicable)
        tent_a = _cents(Decimal(qbi_a) * config.qbi_rate)
        wage_limit = _wage_limit(w2_a, ubia_a, config)
        excess = max(tent_a - wage_limit, 0)
        reduction = _cents(Decimal(excess) * fraction)
        qbi_component = tent_a - reduction

    allowed = min(qbi_component, overall_cap)
    return QBIResult(
        regime=regime,
        phase_in_fraction=fraction,
        tentative_deduction_cents=tentative_full,
        wage_limit_cents=wage_limit,
        qbi_component_cents=qbi_component,
        overall_cap_cents=overall_cap,
        allowed_qbi_deduction_cents=allowed,
    )
