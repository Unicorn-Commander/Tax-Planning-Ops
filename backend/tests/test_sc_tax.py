"""Golden tests for South Carolina tax: personal graduated income tax (on
FEDERAL TAXABLE INCOME) and the flat 5% C-corp income tax.

SC rates/brackets verified against the SC Dept. of Revenue:
  - Personal TY2025: 0% to $3,560; 3% to $17,830; 6% over $17,830 (top rate cut
    from 6.2% in TY2024). Brackets reproduce the official SC1040TT 2025 table
    (Rev. 6/17/25) row-for-row.
  - Corporate: flat 5.0% on SC taxable income.

Dollars x100 = cents. The personal vectors are hand-checked against the
subtraction-method tax baked into the official table.
"""

from __future__ import annotations

from decimal import Decimal

from app.engine_configs import state_corporate_config
from app.engines.corporate import calculate_state_corporate_tax
from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.state_configs import get_state_config
from app.year_configs import state_corporate_config_for


def _sc_personal(fti: int, *, ss: int = 0, retirement: int = 0,
                 status: str = "single", year: int = 2025) -> int:
    """SC starts from federal TAXABLE income, so drive federal_taxable_income_cents."""
    cfg = get_state_config("SC", year)
    assert cfg is not None
    return calculate_state_tax(
        StateTaxInput(
            filing_status=status, federal_agi_cents=fti,
            federal_taxable_income_cents=fti,
            social_security_taxable_cents=ss, retirement_income_cents=retirement,
        ),
        cfg,
    ).total_state_tax_cents


# ---- personal income tax --------------------------------------------------


def test_sc_personal_config_shape() -> None:
    cfg = get_state_config("SC", 2025)
    assert cfg is not None
    assert cfg.has_income_tax is True
    assert cfg.starts_from == "federal_taxable_income"
    assert cfg.flat_rate is None  # graduated, not flat
    # Top marginal rate is 6% for 2025 (the open-ended top bracket).
    top = cfg.brackets_by_status["single"][-1]
    assert top.upper_bound_cents is None
    assert top.rate == Decimal("0.06")


def test_sc_personal_single_2025() -> None:
    # FTI $80,000: 3%*(17,830-3,560) + 6%*(80,000-17,830) = 428.10 + 3,730.20 = $4,158.
    assert _sc_personal(8_000_000) == 415_800


def test_sc_personal_mfj_2025_same_brackets() -> None:
    # SC uses the SAME brackets for every filing status. FTI $250,000:
    # 3%*14,270 + 6%*(250,000-17,830) = 428.10 + 13,930.20 = $14,358.
    assert _sc_personal(25_000_000, status="mfj") == 1_435_800


def test_sc_personal_zero_bracket() -> None:
    # FTI inside the 0% bracket ($3,560) → no tax.
    assert _sc_personal(350_000) == 0


def test_sc_personal_social_security_exempt() -> None:
    # SC fully exempts Social Security. FTI $50,000 incl $15,000 taxable SS →
    # taxed on $35,000: 3%*14,270 + 6%*(35,000-17,830) = 428.10 + 1,030.20 = $1,458.
    assert _sc_personal(5_000_000, ss=1_500_000) == 145_800


def test_sc_personal_2024_top_rate_was_6_2() -> None:
    # TY2024 top rate 6.2% with the lower thresholds (0% to $3,460; 3% to $17,330).
    # FTI $80,000: 3%*(17,330-3,460) + 6.2%*(80,000-17,330) = 416.10 + 3,885.54 = $4,302.
    assert _sc_personal(8_000_000, year=2024) == 430_200
    # And the 2024 config's top rate is 6.2%, not 6%.
    cfg_2024 = get_state_config("SC", 2024)
    assert cfg_2024 is not None
    assert cfg_2024.brackets_by_status["single"][-1].rate == Decimal("0.062")


def test_sc_personal_matches_official_table_row() -> None:
    # Official SC1040TT 2025: taxable income $34,900-$35,000 → tax $1,455.
    # The engine taxes the exact figure; at $34,950 (row midpoint) it is $1,455.
    assert _sc_personal(3_495_000) == 145_500


# ---- corporate income tax -------------------------------------------------


def test_sc_corporate_rate_is_5pct() -> None:
    cfg = state_corporate_config("SC", 2025)
    assert cfg is not None
    assert cfg.corporate_rate == Decimal("0.05")
    # Year-aware selector returns the same flat rate.
    assert state_corporate_config_for("SC", 2026) is not None
    assert state_corporate_config_for("SC", 2026).corporate_rate == Decimal("0.05")


def test_sc_corporate_tax_computes() -> None:
    cfg = state_corporate_config("SC", 2025)
    assert cfg is not None
    # $500,000 SC taxable income * 5% = $25,000.
    result = calculate_state_corporate_tax(50_000_000, cfg)
    assert result.state_corporate_tax_cents == 2_500_000
    assert result.marginal_rate == Decimal("0.05")


def test_non_sc_state_has_no_corporate_config() -> None:
    # Only modeled flat-rate corporate states resolve; others return None.
    assert state_corporate_config("ZZ", 2025) is None
