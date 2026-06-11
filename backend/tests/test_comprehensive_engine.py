"""Integration tests for the comprehensive return orchestrator.

Verifies it composes the (separately golden-tested) federal, SS, CTC, and AMT
engines correctly. Round federal config (10/20/30%, std $15k); the SS/CTC/AMT
sub-engines use their real 2025 configs.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.amt import ty2025_amt_config
from app.engines.comprehensive import ComprehensiveInput, calculate_comprehensive
from app.engines.ctc import ty2025_ctc_config
from app.engines.form1040 import (
    AuxiliaryConfig,
    Form1040Inputs,
    RateBracket,
    TaxConfig,
    calculate_form1040,
)
from app.engines.ss_taxability import ty2025_ss_config


def _config() -> TaxConfig:
    return TaxConfig(
        tax_year=2025,
        filing_status="single",
        standard_deduction_cents=1_500_000,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.10")),
            RateBracket(lower_bound_cents=1_000_000, upper_bound_cents=5_000_000, rate=Decimal("0.20")),
            RateBracket(lower_bound_cents=5_000_000, upper_bound_cents=None, rate=Decimal("0.30")),
        ],
        auxiliary=AuxiliaryConfig(
            ltcg_brackets=[
                RateBracket(lower_bound_cents=0, upper_bound_cents=4_000_000, rate=Decimal("0")),
                RateBracket(lower_bound_cents=4_000_000, upper_bound_cents=None, rate=Decimal("0.15")),
            ],
            niit_threshold_cents=10_000_000,
            niit_rate=Decimal("0.0380"),
            additional_medicare_threshold_cents=10_000_000,
            additional_medicare_rate=Decimal("0.0090"),
            capital_loss_limit_cents=300_000,
        ),
    )


def test_plain_equals_form1040() -> None:
    inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    res = calculate_comprehensive(ComprehensiveInput(form1040=inputs), _config())
    assert res.total_tax_cents == calculate_form1040(inputs, _config()).total_tax_cents == 600_000
    assert res.amt_cents == 0
    assert res.refundable_credits_cents == 0
    assert res.social_security is None and res.ctc is None


def test_social_security_folds_into_income() -> None:
    # single: gross SS 30,000, wages 40,000 → provisional 55,000 → taxable 22,350.
    # total income = wages 40,000 + taxable SS 22,350 = 62,350.
    res = calculate_comprehensive(
        ComprehensiveInput(
            form1040=Form1040Inputs(filing_status="single", wages_cents=4_000_000),
            social_security_benefits_gross_cents=3_000_000,
        ),
        _config(),
        ss_config=ty2025_ss_config(),
    )
    assert res.social_security is not None
    assert res.social_security.taxable_social_security_cents == 2_235_000
    assert res.federal.total_income_cents == 6_235_000


def test_ctc_two_pass_reduces_tax() -> None:
    # wages 50,000 → income tax 6,000; 2 children, MAGI 50k (no phaseout) → CTC 4,400.
    # nonrefundable 4,400 → tax after credit 1,600; ACTC 0 (fully used).
    res = calculate_comprehensive(
        ComprehensiveInput(
            form1040=Form1040Inputs(filing_status="single", wages_cents=5_000_000),
            qualifying_children=2,
        ),
        _config(),
        ctc_config=ty2025_ctc_config(),
    )
    assert res.ctc is not None
    assert res.ctc.nonrefundable_ctc_odc_cents == 440_000
    assert res.refundable_credits_cents == 0
    assert res.total_tax_cents == 160_000  # 600,000 − 440,000


def test_amt_adds_when_tentative_exceeds_regular() -> None:
    # wages 200,000 + $150,000 ISO preference. Regular income tax 49,500;
    # AMTI = 185,000 + 15,000 std add-back + 150,000 ISO = 350,000; exemption 88,100;
    # excess 261,900 > 239,100 → 0.28·261,900 − 4,782 = 68,550 TMT;
    # AMT = 68,550 − 49,500 = 19,050.
    res = calculate_comprehensive(
        ComprehensiveInput(
            form1040=Form1040Inputs(filing_status="single", wages_cents=20_000_000),
            amt_other_preferences_cents=15_000_000,
        ),
        _config(),
        amt_config=ty2025_amt_config(),
    )
    assert res.amt is not None
    assert res.amt.amt_applies is True
    assert res.amt_cents == 1_905_000
    # total = regular total (incl. Add'l Medicare) + AMT
    assert res.total_tax_cents == res.federal.total_tax_cents + res.amt_cents


def test_all_engines_compose() -> None:
    # Sanity: SS + CTC + AMT configs all supplied, modest case → no crash, AMT 0.
    res = calculate_comprehensive(
        ComprehensiveInput(
            form1040=Form1040Inputs(filing_status="single", wages_cents=5_000_000),
            social_security_benefits_gross_cents=1_000_000,
            qualifying_children=1,
        ),
        _config(),
        ss_config=ty2025_ss_config(),
        ctc_config=ty2025_ctc_config(),
        amt_config=ty2025_amt_config(),
    )
    assert res.total_tax_cents == res.federal.total_tax_cents + res.amt_cents
    assert res.amt_cents == 0
