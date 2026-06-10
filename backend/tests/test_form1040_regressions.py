"""Regression goldens for the four review-confirmed engine fixes, computed
against the REAL seeded constants (IRS Rev. Proc. 2024-40 / 2025-32 + OBBBA),
inline so the engine math is locked independent of DB seeding.

Expected values are hand-computed to the cent (see the arithmetic in each
test's comment).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.engines.form1040 import (
    AuxiliaryConfig,
    Form1040Inputs,
    RateBracket,
    TaxConfig,
    bracket_walk,
    calculate_form1040,
)

# ---- real federal configs (cents) -----------------------------------------

_ORDINARY = {
    (2025, "single"): [
        (0, 1192500, "0.10"), (1192500, 4847500, "0.12"), (4847500, 10335000, "0.22"),
        (10335000, 19730000, "0.24"), (19730000, 25052500, "0.32"),
        (25052500, 62635000, "0.35"), (62635000, None, "0.37"),
    ],
    (2025, "mfj"): [
        (0, 2385000, "0.10"), (2385000, 9695000, "0.12"), (9695000, 20670000, "0.22"),
        (20670000, 39460000, "0.24"), (39460000, 50105000, "0.32"),
        (50105000, 75160000, "0.35"), (75160000, None, "0.37"),
    ],
    (2026, "single"): [
        (0, 1240000, "0.10"), (1240000, 5040000, "0.12"), (5040000, 10570000, "0.22"),
        (10570000, 20177500, "0.24"), (20177500, 25622500, "0.32"),
        (25622500, 64060000, "0.35"), (64060000, None, "0.37"),
    ],
}
_LTCG = {
    (2025, "single"): [(0, 4835000, "0.00"), (4835000, 53340000, "0.15"), (53340000, None, "0.20")],
    (2025, "mfj"): [(0, 9670000, "0.00"), (9670000, 60005000, "0.15"), (60005000, None, "0.20")],
    (2026, "single"): [(0, 4945000, "0.00"), (4945000, 54550000, "0.15"), (54550000, None, "0.20")],
}
_STD = {(2025, "single"): 1575000, (2025, "mfj"): 3150000, (2026, "single"): 1610000}


def cfg(year: int, status: str) -> TaxConfig:
    def rows(spec: list) -> list[RateBracket]:
        return [
            RateBracket(lower_bound_cents=lo, upper_bound_cents=hi, rate=Decimal(r))
            for lo, hi, r in spec
        ]

    return TaxConfig(
        tax_year=year,
        filing_status=status,  # type: ignore[arg-type]
        standard_deduction_cents=_STD[(year, status)],
        ordinary_brackets=rows(_ORDINARY[(year, status)]),
        auxiliary=AuxiliaryConfig(
            ltcg_brackets=rows(_LTCG[(year, status)]),
            niit_threshold_cents=25000000 if status == "mfj" else 20000000,
            niit_rate=Decimal("0.038"),
            additional_medicare_threshold_cents=25000000 if status == "mfj" else 20000000,
            additional_medicare_rate=Decimal("0.009"),
            capital_loss_limit_cents=300000,
            qbi_limit_rate=Decimal("0.20"),
        ),
    )


# canonical scenario: 2025 single, $185k wages, $1.2k int, $3.5k QDIV, $12k LTCG
_CANON = dict(
    filing_status="single", wages_cents=18_500_000, taxable_interest_cents=120_000,
    ordinary_dividends_cents=350_000, qualified_dividends_cents=350_000,
)


def test_long_term_gain_canonical_to_the_cent() -> None:
    # ordinary taxable 170,450 -> 33,755.00; pref 15,500 LTCG @15% -> 2,325.00;
    # NIIT min(16,700 inv, AGI 201,700-200,000) = 1,700 @3.8% -> 64.60.
    r = calculate_form1040(
        Form1040Inputs(**_CANON, net_long_term_capital_gain_cents=1_200_000), cfg(2025, "single")
    )
    assert r.ordinary_tax_cents == 3_375_500
    assert r.preferential_tax_cents == 232_500
    assert r.niit_cents == 6_460
    assert r.total_tax_cents == 3_614_460
    assert r.marginal_rate == Decimal("0.24")


def test_short_term_gain_taxed_higher_than_long_term() -> None:
    lt = calculate_form1040(
        Form1040Inputs(**_CANON, net_long_term_capital_gain_cents=1_200_000), cfg(2025, "single")
    )
    st = calculate_form1040(
        Form1040Inputs(**_CANON, net_short_term_capital_gain_cents=1_200_000), cfg(2025, "single")
    )
    assert st.total_tax_cents > lt.total_tax_cents  # ST is ordinary-rate


def test_combined_line7_falls_back_to_long_term_with_assumption_flag() -> None:
    combined = calculate_form1040(
        Form1040Inputs(**_CANON, capital_gain_loss_cents=1_200_000), cfg(2025, "single")
    )
    split = calculate_form1040(
        Form1040Inputs(**_CANON, net_long_term_capital_gain_cents=1_200_000), cfg(2025, "single")
    )
    assert combined.total_tax_cents == split.total_tax_cents
    assert any("capital_gain_treated_as_long_term" in a for a in combined.assumptions)


def test_nonrefundable_credits_do_not_offset_niit() -> None:
    # Huge credits zero out income tax but NIIT (6,460) must survive.
    r = calculate_form1040(
        Form1040Inputs(
            **_CANON, net_long_term_capital_gain_cents=1_200_000,
            nonrefundable_credits_cents=99_000_000,
        ),
        cfg(2025, "single"),
    )
    assert r.total_tax_cents == 6_460


def test_qbi_clamped_to_199a_limit() -> None:
    # single 2025, wages 100k, excessive QBI request 50k.
    # TI before QBI = 100,000-15,750 = 84,250; cap = 20% = 16,850.
    r = calculate_form1040(
        Form1040Inputs(filing_status="single", wages_cents=10_000_000, qbi_deduction_cents=5_000_000),
        cfg(2025, "single"),
    )
    assert r.qbi_deduction_cents == 1_685_000
    assert any("qbi_clamped" in a for a in r.assumptions)


def test_bracket_walk_is_order_independent() -> None:
    rows = [
        RateBracket(lower_bound_cents=lo, upper_bound_cents=hi, rate=Decimal(r))
        for lo, hi, r in _ORDINARY[(2025, "single")]
    ]
    scrambled = [rows[3], rows[0], rows[6], rows[2], rows[1], rows[5], rows[4]]
    assert bracket_walk(17_045_000, scrambled) == bracket_walk(17_045_000, rows)


def test_mfj_golden_to_the_cent() -> None:
    # MFJ 2025, $200k wages: taxable 168,500 -> 26,898.00, marginal 22%.
    r = calculate_form1040(
        Form1040Inputs(filing_status="mfj", wages_cents=20_000_000), cfg(2025, "mfj")
    )
    assert r.ordinary_tax_cents == 2_689_800
    assert r.marginal_rate == Decimal("0.22")


@pytest.mark.parametrize("year", [2025, 2026])
def test_monotonic_over_real_years(year: int) -> None:
    c = cfg(year, "single")
    prev = 0
    for w in range(0, 80_000_000, 1_000_000):
        r = calculate_form1040(Form1040Inputs(filing_status="single", wages_cents=w), c)
        assert r.total_tax_cents >= prev
        assert Decimal("0") <= r.effective_rate <= Decimal("0.37")
        prev = r.total_tax_cents
