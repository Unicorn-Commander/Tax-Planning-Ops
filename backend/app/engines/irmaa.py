"""Medicare IRMAA — Income-Related Monthly Adjustment Amount, plan year 2025.

Surcharges are set from the beneficiary's MAGI two years prior (2023 MAGI →
2025 premiums). This engine returns the Part B and Part D surcharges for a given
MAGI + filing status, and — because this is a PLANNING tool — the distance to
the next IRMAA cliff, the annual cost of crossing it, and the room to drop a
tier. Tiers use the SSA convention of strict ">" at each breakpoint except the
top tier which is inclusive.

2025 figures from SSA POMS HI 01101.020. All money is integer cents.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FilingStatus = Literal["single", "mfj", "mfs_lived_with_spouse"]

# Surcharge schedule indexed by tier 0..5: (part_b_cents, part_d_cents) per month.
_TIER_SURCHARGES: list[tuple[int, int]] = [
    (0, 0),
    (7_400, 1_370),
    (18_500, 3_530),
    (29_590, 5_700),
    (40_690, 7_860),
    (44_390, 8_580),
]

# Per-status cliffs: (magi_cents_breakpoint, tier_entered). The last entry is the
# top tier and uses ">=" rather than ">".
_CLIFFS: dict[str, list[tuple[int, int]]] = {
    "single": [
        (10_600_000, 1), (13_300_000, 2), (16_700_000, 3), (20_000_000, 4), (50_000_000, 5),
    ],
    "mfj": [
        (21_200_000, 1), (26_600_000, 2), (33_400_000, 3), (40_000_000, 4), (75_000_000, 5),
    ],
    # MFS living with spouse skips straight to tier 4, then tier 5.
    "mfs_lived_with_spouse": [
        (10_600_000, 4), (39_400_000, 5),
    ],
}


class IRMAAConfig(BaseModel):
    plan_year: int
    part_b_base_cents: int
    tier_surcharges: list[tuple[int, int]]
    cliffs: dict[str, list[tuple[int, int]]]


def ty2025_irmaa_config() -> IRMAAConfig:
    return IRMAAConfig(
        plan_year=2025,
        part_b_base_cents=18_500,  # $185.00/mo
        tier_surcharges=_TIER_SURCHARGES,
        cliffs=_CLIFFS,
    )


class IRMAAInput(BaseModel):
    filing_status: FilingStatus
    magi_cents: int  # the 2-year-prior MAGI that governs this plan year
    both_spouses_enrolled: bool = False  # MFJ household doubling


class IRMAAResult(BaseModel):
    irmaa_tier: int
    part_b_surcharge_monthly_cents: int
    part_b_total_monthly_cents: int
    part_d_surcharge_monthly_cents: int
    total_irmaa_annual_cents: int  # (B + D surcharge) × 12, single beneficiary
    household_total_irmaa_annual_cents: int
    next_cliff_threshold_cents: int | None
    distance_to_next_cliff_cents: int | None
    cliff_cost_annual_cents: int | None  # added annual surcharge if MAGI crosses next cliff
    room_to_drop_one_tier_cents: int | None
    assumptions: list[str] = Field(default_factory=list)


def calculate_irmaa(inputs: IRMAAInput, config: IRMAAConfig) -> IRMAAResult:
    cliffs = config.cliffs.get(inputs.filing_status)
    if cliffs is None:
        raise ValueError(f"no IRMAA cliffs configured for {inputs.filing_status}")

    magi = inputs.magi_cents
    tier = 0
    current_lower_bound = 0  # the cliff that put us in the current tier
    for idx, (breakpoint_cents, target_tier) in enumerate(cliffs):
        is_top = idx == len(cliffs) - 1
        crossed = magi >= breakpoint_cents if is_top else magi > breakpoint_cents
        if crossed:
            tier = target_tier
            current_lower_bound = breakpoint_cents
        else:
            break

    part_b_surcharge, part_d_surcharge = config.tier_surcharges[tier]
    part_b_total = config.part_b_base_cents + part_b_surcharge
    annual = (part_b_surcharge + part_d_surcharge) * 12
    doubles = inputs.filing_status == "mfj" and inputs.both_spouses_enrolled
    household = annual * 2 if doubles else annual

    # Next cliff: the first breakpoint strictly above the current MAGI.
    next_cliff: int | None = None
    cliff_cost: int | None = None
    next_tier: int | None = None
    for breakpoint_cents, target_tier in cliffs:
        if breakpoint_cents > magi:
            next_cliff = breakpoint_cents
            next_tier = target_tier
            break
    if next_cliff is not None and next_tier is not None:
        nb_b, nb_d = config.tier_surcharges[next_tier]
        cliff_cost = ((nb_b - part_b_surcharge) + (nb_d - part_d_surcharge)) * 12
    distance = next_cliff - magi if next_cliff is not None else None

    # Room to drop a tier: how far MAGI sits above the current tier's lower bound.
    room_to_drop = magi - current_lower_bound if tier > 0 else None

    return IRMAAResult(
        irmaa_tier=tier,
        part_b_surcharge_monthly_cents=part_b_surcharge,
        part_b_total_monthly_cents=part_b_total,
        part_d_surcharge_monthly_cents=part_d_surcharge,
        total_irmaa_annual_cents=annual,
        household_total_irmaa_annual_cents=household,
        next_cliff_threshold_cents=next_cliff,
        distance_to_next_cliff_cents=distance,
        cliff_cost_annual_cents=cliff_cost,
        room_to_drop_one_tier_cents=room_to_drop,
    )
