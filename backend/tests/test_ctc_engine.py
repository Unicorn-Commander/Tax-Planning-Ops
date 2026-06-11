"""Golden tests for the CTC/ODC/ACTC engine (Schedule 8812, TY2025).

The three adversarially-verified vectors. Amounts in dollars ×100 = cents.
"""

from __future__ import annotations

from app.engines.ctc import CTCInput, calculate_ctc, ty2025_ctc_config

CFG = ty2025_ctc_config()


def test_v1_no_phaseout_fully_nonrefundable() -> None:
    # MFJ, 2 children + 1 ODC, MAGI 100k, tax 9k.
    # CTC 4,400 + ODC 500 = 4,900; no phaseout; min(4,900, 9,000)=4,900; ACTC 0.
    out = calculate_ctc(
        CTCInput(filing_status="mfj", qualifying_children=2, other_dependents=1,
                 magi_cents=10_000_000, tax_liability_cents=900_000, earned_income_cents=10_000_000),
        CFG,
    )
    assert out.credit_before_phaseout_cents == 490_000
    assert out.phaseout_reduction_cents == 0
    assert out.nonrefundable_ctc_odc_cents == 490_000
    assert out.refundable_actc_cents == 0


def test_v2_low_tax_actc_earned_income_binds() -> None:
    # HOH, 3 children, MAGI 30k, tax 500, earned 30k.
    # CTC 6,600; nonref min(6,600,500)=500; remaining 6,100; cap 3·1,700=5,100;
    # 15%·(30,000−2,500)=4,125 → ACTC min(6,100,5,100,4,125)=4,125.
    out = calculate_ctc(
        CTCInput(filing_status="hoh", qualifying_children=3, other_dependents=0,
                 magi_cents=3_000_000, tax_liability_cents=50_000, earned_income_cents=3_000_000),
        CFG,
    )
    assert out.credit_before_phaseout_cents == 660_000
    assert out.nonrefundable_ctc_odc_cents == 50_000
    assert out.refundable_actc_cents == 412_500


def test_v3_phaseout_roundup_fully_nonrefundable() -> None:
    # MFJ, 3 children + 1 ODC, MAGI 440,400, tax 80k.
    # combined 7,100; excess 40,400 → round up 41,000 → 5% = 2,050;
    # after 5,050; min(5,050, 80,000)=5,050; ACTC 0.
    out = calculate_ctc(
        CTCInput(filing_status="mfj", qualifying_children=3, other_dependents=1,
                 magi_cents=44_040_000, tax_liability_cents=8_000_000, earned_income_cents=44_040_000),
        CFG,
    )
    assert out.credit_before_phaseout_cents == 710_000
    assert out.phaseout_reduction_cents == 205_000
    assert out.credit_after_phaseout_cents == 505_000
    assert out.nonrefundable_ctc_odc_cents == 505_000
    assert out.refundable_actc_cents == 0


def test_config_constants_guard() -> None:
    assert CFG.ctc_per_child_cents == 220_000  # $2,200 post-OBBBA
    assert CFG.odc_per_dependent_cents == 50_000
    assert CFG.phaseout_threshold_mfj_cents == 40_000_000
    assert CFG.phaseout_threshold_other_cents == 20_000_000
    assert CFG.refundable_cap_per_child_cents == 170_000
    assert CFG.earned_income_floor_cents == 250_000
