"""Unit tests for the multi-entity business aggregation (no DB).

Maps stored BusinessEntity rows → passthrough → SE tax + §199A QBI aggregate.
Hand-computed: a Sole-prop + S-corp + rental owner. Dollars ×100 = cents.
"""

from __future__ import annotations

from app.models.entity import BusinessEntity
from app.services.entities import aggregate_business


def _entity(kind: str, amount: int, **kw: object) -> BusinessEntity:
    defaults = dict(
        name="", amount_cents=amount, w2_wages_paid_cents=0, ubia_cents=0,
        guaranteed_payments_cents=0, shareholder_w2_wages_cents=0,
        is_general_partner=True, is_sstb=False, is_qbi=False,
    )
    defaults.update(kw)
    return BusinessEntity(kind=kind, **defaults)  # type: ignore[arg-type]


def test_empty_unavailable() -> None:
    out = aggregate_business([], filing_status="single", taxable_income_before_qbi_cents=0)
    assert out["available"] is False


def test_mixed_owner_se_and_qbi() -> None:
    entities = [
        _entity("schedule_c", 10_000_000),       # $100k Sch C → SE + QBI
        _entity("s_corp_k1", 5_000_000),          # $50k S-corp → QBI, NOT SE
        _entity("schedule_e", 2_000_000, is_qbi=False),  # $20k rental → Sch1 only
    ]
    out = aggregate_business(
        entities,
        filing_status="single",
        taxable_income_before_qbi_cents=15_000_000,  # below QBI threshold
        net_capital_gain_cents=0,
    )
    assert out["available"] is True
    # Schedule 1 = 100k + 50k + 20k.
    assert out["schedule_1_income_cents"] == 17_000_000
    # SE base = only the Sch C.
    assert out["se_earnings_base_cents"] == 10_000_000
    assert out["se_tax_cents"] == 1_412_900  # $14,129 (matches SE golden v1)
    assert out["half_se_deduction_cents"] == 706_500
    # QBI below-threshold: 20% of (100k + 50k) = 30,000; capped at 20%·150k = 30,000.
    assert out["qbi_deduction_cents"] == 3_000_000
    assert len(out["qbi_per_business"]) == 2  # rental excluded (is_qbi=False)


def test_general_vs_limited_partner_se() -> None:
    general = aggregate_business(
        [_entity("partnership_k1", 8_000_000, is_general_partner=True)],
        filing_status="single", taxable_income_before_qbi_cents=8_000_000,
    )
    limited = aggregate_business(
        [_entity("partnership_k1", 8_000_000, is_general_partner=False)],
        filing_status="single", taxable_income_before_qbi_cents=8_000_000,
    )
    # General partner's K-1 ordinary income is SE-taxable; limited partner's isn't.
    assert general["se_earnings_base_cents"] == 8_000_000
    assert limited["se_earnings_base_cents"] == 0
    # Both still flow to Schedule 1 and QBI.
    assert general["schedule_1_income_cents"] == limited["schedule_1_income_cents"] == 8_000_000
