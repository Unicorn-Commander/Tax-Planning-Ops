"""Goal-aware finding generation — the client's objectives turned into
engine-computed levers. Pure (no DB); the trajectory is covered by service
integration."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.engines.charitable import charitable_config_for
from app.services.strategist_context import goal_aware_findings
from app.year_configs import corporate_config_for


def _profile(**overrides: Any) -> SimpleNamespace:
    base = dict(
        primary_objective="no_preference",
        retirement_target_year=None,
        liquidity_event="none",
        liquidity_event_year=None,
        liquidity_event_amount_cents=0,
        charitable_intent="none",
        annual_giving_cents=0,
        estate_priority="none",
        planned_relocation_state=None,
        relocation_year=None,
        roth_preference="no_preference",
        risk_tolerance="moderate",
        cash_flow_sensitivity="medium",
        education_funding=False,
        business_succession="none",
        notes=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _call(profile: SimpleNamespace, **kw: Any) -> list[dict[str, Any]]:
    defaults = dict(
        tax_year=2026,
        marginal_rate=Decimal("0.24"),
        agi_cents=40_000_000,
        itemized_deduction_cents=1_000_000,
        standard_deduction_cents=3_220_000,
        ira_taxable_cents=0,
        primary_state="CA",
        charitable_config=charitable_config_for(2026),
        corporate_config=corporate_config_for(2026),
    )
    defaults.update(kw)
    return goal_aware_findings(profile=profile, **defaults)


def test_no_profile_yields_no_findings() -> None:
    assert goal_aware_findings(
        profile=None, tax_year=2026, marginal_rate=Decimal("0.24"), agi_cents=0,
        itemized_deduction_cents=0, standard_deduction_cents=3_220_000, ira_taxable_cents=0,
        primary_state="CA", charitable_config=charitable_config_for(2026),
        corporate_config=corporate_config_for(2026),
    ) == []


def test_charitable_intent_drives_bunching_finding() -> None:
    findings = _call(_profile(charitable_intent="high", annual_giving_cents=1_500_000))
    titles = [f["title"] for f in findings]
    assert any("Bunch charitable gifts" in t for t in titles)
    bunch = next(f for f in findings if "Bunch" in f["title"])
    assert bunch["impact_kind"] == "savings"
    assert bunch["estimated_impact_cents"] > 0


def test_business_sale_drives_qsbs_finding() -> None:
    findings = _call(
        _profile(liquidity_event="business_sale", liquidity_event_amount_cents=500_000_000)
    )
    qsbs = next(f for f in findings if "QSBS" in f["title"])
    assert qsbs["category"] == "liquidity"
    # 100% exclusion on $5M vs a ~23.8% taxable sale → > $1M saved.
    assert qsbs["estimated_impact_cents"] > 100_000_000


def test_relocation_to_no_tax_state_drives_timing_finding() -> None:
    findings = _call(
        _profile(
            planned_relocation_state="TX",
            liquidity_event="business_sale",
            liquidity_event_amount_cents=500_000_000,
        ),
        primary_state="CA",
    )
    reloc = next(f for f in findings if "residency" in f["title"])
    assert reloc["category"] == "state"
    assert reloc["estimated_impact_cents"] > 0  # CA tax avoided vs TX (no income tax)


def test_retirement_year_drives_roth_window_info() -> None:
    findings = _call(_profile(retirement_target_year=2031), tax_year=2026)
    roth = next(f for f in findings if "Roth-conversion window" in f["title"])
    assert roth["impact_kind"] == "info"


def test_qcd_appears_for_retired_charitable_donor() -> None:
    findings = _call(
        _profile(
            charitable_intent="moderate",
            annual_giving_cents=2_000_000,
            retirement_target_year=2024,  # already retired relative to 2026
        ),
        tax_year=2026,
        marginal_rate=Decimal("0.22"),
    )
    assert any("Qualified Charitable Distribution" in f["title"] for f in findings)
