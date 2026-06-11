"""Golden tests for IRMAA 2025 (2-year MAGI lookback) + planning helpers.

Three adversarially-verified vectors (with the reviewer's two cliff-cost
corrections applied: 1591.20 and 530.40). Dollars ×100 = cents.
"""

from __future__ import annotations

from app.engines.irmaa import IRMAAInput, calculate_irmaa, ty2025_irmaa_config

CFG = ty2025_irmaa_config()


def test_single_tier0_with_cliff_planning() -> None:
    # single MAGI 100,000 → tier 0; next cliff 106,000, distance 6,000;
    # cliff cost into T1 = (74.00+13.70)×12 = 1,052.40.
    out = calculate_irmaa(IRMAAInput(filing_status="single", magi_cents=10_000_000), CFG)
    assert out.irmaa_tier == 0
    assert out.part_b_surcharge_monthly_cents == 0
    assert out.part_b_total_monthly_cents == 18_500
    assert out.total_irmaa_annual_cents == 0
    assert out.next_cliff_threshold_cents == 10_600_000
    assert out.distance_to_next_cliff_cents == 600_000
    assert out.cliff_cost_annual_cents == 105_240  # $1,052.40
    assert out.room_to_drop_one_tier_cents is None


def test_mfj_tier2_both_enrolled() -> None:
    # MFJ MAGI 300,000 → tier 2; B surcharge 185.00 total 370.00; D 35.30;
    # annual (185+35.30)×12 = 2,643.60; household ×2 = 5,287.20.
    # next cliff 334,000 distance 34,000; cliff cost (110.90+21.70)×12 = 1,591.20;
    # room to drop = 300,000 − 266,000 = 34,000.
    out = calculate_irmaa(
        IRMAAInput(filing_status="mfj", magi_cents=30_000_000, both_spouses_enrolled=True), CFG
    )
    assert out.irmaa_tier == 2
    assert out.part_b_surcharge_monthly_cents == 18_500
    assert out.part_b_total_monthly_cents == 37_000
    assert out.part_d_surcharge_monthly_cents == 3_530
    assert out.total_irmaa_annual_cents == 264_360  # $2,643.60
    assert out.household_total_irmaa_annual_cents == 528_720  # $5,287.20
    assert out.next_cliff_threshold_cents == 33_400_000
    assert out.distance_to_next_cliff_cents == 3_400_000
    assert out.cliff_cost_annual_cents == 159_120  # $1,591.20 (reviewer-corrected)
    assert out.room_to_drop_one_tier_cents == 3_400_000


def test_mfs_lived_with_spouse_jumps_to_tier4() -> None:
    # MFS-with-spouse MAGI 150,000 → tier 4; B surcharge 406.90 total 591.90; D 78.60;
    # annual (406.90+78.60)×12 = 5,826.00. next cliff 394,000 distance 244,000;
    # cliff cost (37.00+7.20)×12 = 530.40; room to drop = 150,000 − 106,000 = 44,000.
    out = calculate_irmaa(
        IRMAAInput(filing_status="mfs_lived_with_spouse", magi_cents=15_000_000), CFG
    )
    assert out.irmaa_tier == 4
    assert out.part_b_surcharge_monthly_cents == 40_690
    assert out.part_b_total_monthly_cents == 59_190
    assert out.part_d_surcharge_monthly_cents == 7_860
    assert out.total_irmaa_annual_cents == 582_600  # $5,826.00
    assert out.next_cliff_threshold_cents == 39_400_000
    assert out.distance_to_next_cliff_cents == 24_400_000
    assert out.cliff_cost_annual_cents == 53_040  # $530.40 (reviewer-corrected)
    assert out.room_to_drop_one_tier_cents == 4_400_000


def test_top_tier_inclusive_boundary() -> None:
    # single MAGI exactly 500,000 → top tier 5 (inclusive boundary).
    out = calculate_irmaa(IRMAAInput(filing_status="single", magi_cents=50_000_000), CFG)
    assert out.irmaa_tier == 5
    assert out.next_cliff_threshold_cents is None
    assert out.cliff_cost_annual_cents is None


def test_config_constants_guard() -> None:
    assert CFG.part_b_base_cents == 18_500
    assert CFG.tier_surcharges[4] == (40_690, 7_860)
    assert CFG.tier_surcharges[5] == (44_390, 8_580)
    assert CFG.cliffs["single"][0] == (10_600_000, 1)
    assert CFG.cliffs["mfj"][2] == (33_400_000, 3)
