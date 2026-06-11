"""Golden tests for the multi-entity pass-through aggregation engine (TY2025).

Pure routing/aggregation — every expected value is hand-summed in the comment.
Dollars ×100 = cents.
"""

from __future__ import annotations

from app.engines.passthrough import (
    PartnershipK1Entity,
    PassthroughInput,
    ScheduleCEntity,
    ScheduleERental,
    SCorpK1Entity,
    aggregate_passthrough,
)


def test_sole_prop_only() -> None:
    # Single Sch C: $100,000 net profit. SE base = 100k, Sch 1 = 100k,
    # one QBI component of 100k (non-SSTB).
    out = aggregate_passthrough(
        PassthroughInput(
            schedule_c=[
                ScheduleCEntity(
                    name="Consulting",
                    net_profit_cents=10_000_000,
                    w2_wages_paid_cents=3_000_000,
                    ubia_cents=1_000_000,
                )
            ]
        )
    )
    assert out.total_se_earnings_base_cents == 10_000_000
    assert out.total_schedule_1_income_cents == 10_000_000
    assert out.total_qualified_business_income_cents == 10_000_000
    assert len(out.qbi_components) == 1
    comp = out.qbi_components[0]
    assert comp.source == "schedule_c"
    assert comp.qbi_cents == 10_000_000
    assert comp.w2_wages_cents == 3_000_000
    assert comp.ubia_cents == 1_000_000
    assert comp.is_sstb is False
    assert out.assumptions == []


def test_general_partner_is_se() -> None:
    # General partner K-1 box 1 $80,000. SE base = 80k, Sch 1 = 80k, QBI 80k.
    out = aggregate_passthrough(
        PassthroughInput(
            partnerships=[
                PartnershipK1Entity(
                    name="GP Fund",
                    ordinary_income_cents=8_000_000,
                    is_general_partner=True,
                )
            ]
        )
    )
    assert out.total_se_earnings_base_cents == 8_000_000  # general → SE
    assert out.total_schedule_1_income_cents == 8_000_000
    assert out.total_qualified_business_income_cents == 8_000_000
    assert len(out.qbi_components) == 1
    assert out.qbi_components[0].source == "partnership_k1"


def test_limited_partner_not_se() -> None:
    # Limited partner K-1 box 1 $80,000. SE base = 0, Sch 1 = 80k, QBI 80k.
    out = aggregate_passthrough(
        PassthroughInput(
            partnerships=[
                PartnershipK1Entity(
                    name="LP Fund",
                    ordinary_income_cents=8_000_000,
                    is_general_partner=False,
                )
            ]
        )
    )
    assert out.total_se_earnings_base_cents == 0  # limited → not SE
    assert out.total_schedule_1_income_cents == 8_000_000
    assert out.total_qualified_business_income_cents == 8_000_000


def test_scorp_no_se_but_qbi() -> None:
    # S-corp K-1 box 1 $120,000, shareholder salary $60,000, business W-2 $90,000.
    # SE base = 0 (S-corp advantage), Sch 1 = 120k, QBI = 120k with 90k wages.
    out = aggregate_passthrough(
        PassthroughInput(
            s_corps=[
                SCorpK1Entity(
                    name="Acme S",
                    ordinary_income_cents=12_000_000,
                    w2_wages_paid_cents=9_000_000,
                    ubia_cents=2_000_000,
                    shareholder_w2_wages_cents=6_000_000,
                )
            ]
        )
    )
    assert out.total_se_earnings_base_cents == 0
    assert out.total_schedule_1_income_cents == 12_000_000
    assert out.total_qualified_business_income_cents == 12_000_000
    comp = out.qbi_components[0]
    assert comp.source == "s_corp_k1"
    assert comp.qbi_cents == 12_000_000
    assert comp.w2_wages_cents == 9_000_000


def test_guaranteed_payments_se_not_qbi() -> None:
    # General partner: box 1 $50,000 + guaranteed payments $40,000.
    # SE base = 50k + 40k = 90k. Sch 1 = 50k + 40k = 90k.
    # QBI = 50k only (guaranteed payments excluded from QBI).
    out = aggregate_passthrough(
        PassthroughInput(
            partnerships=[
                PartnershipK1Entity(
                    name="Ops LLP",
                    ordinary_income_cents=5_000_000,
                    is_general_partner=True,
                    guaranteed_payments_cents=4_000_000,
                )
            ]
        )
    )
    assert out.total_se_earnings_base_cents == 9_000_000  # 50k + 40k
    assert out.total_schedule_1_income_cents == 9_000_000  # 50k + 40k
    assert out.total_qualified_business_income_cents == 5_000_000  # GP excluded
    assert len(out.qbi_components) == 1
    assert out.qbi_components[0].qbi_cents == 5_000_000
    assert any("guaranteed_payments_treated_as_se_income" in a for a in out.assumptions)


def test_rental_sch1_only_qbi_off_by_default() -> None:
    # Rental net $30,000. Sch 1 = 30k, SE base = 0, NO QBI component (default).
    out = aggregate_passthrough(
        PassthroughInput(
            rentals=[ScheduleERental(name="Duplex", net_rental_cents=3_000_000)]
        )
    )
    assert out.total_se_earnings_base_cents == 0
    assert out.total_schedule_1_income_cents == 3_000_000
    assert out.total_qualified_business_income_cents == 0
    assert out.qbi_components == []
    assert any("passive_loss_limits_ignored" in a for a in out.assumptions)
    assert any("rental_qbi_default_off" in a for a in out.assumptions)


def test_mixed_multi_entity_owner() -> None:
    # A real business owner combining everything:
    #   Sch C net profit:                    $90,000  (SE, QBI)
    #   General partner box 1:               $40,000  (SE, QBI)
    #     + guaranteed payments:             $20,000  (SE, Sch1, NOT QBI)
    #   Limited partner box 1:               $25,000  (Sch1, QBI, NOT SE)
    #   S-corp box 1:                       $110,000  (Sch1, QBI, NOT SE)
    #   Rental (rises to trade/business):    $15,000  (Sch1, QBI when flagged)
    #
    # SE base   = 90,000 + 40,000 + 20,000                         = $150,000
    # Sch 1     = 90,000 + 40,000 + 20,000 + 25,000 + 110,000 + 15,000 = $300,000
    # QBI total = 90,000 + 40,000 + 25,000 + 110,000 + 15,000      = $280,000
    #             (guaranteed payments excluded)
    # QBI components = 5 (Sch C, GP, LP, S-corp, rental-as-TB)
    out = aggregate_passthrough(
        PassthroughInput(
            schedule_c=[
                ScheduleCEntity(name="Studio", net_profit_cents=9_000_000)
            ],
            partnerships=[
                PartnershipK1Entity(
                    name="GP Co",
                    ordinary_income_cents=4_000_000,
                    is_general_partner=True,
                    guaranteed_payments_cents=2_000_000,
                ),
                PartnershipK1Entity(
                    name="LP Co",
                    ordinary_income_cents=2_500_000,
                    is_general_partner=False,
                ),
            ],
            s_corps=[
                SCorpK1Entity(name="Holdco S", ordinary_income_cents=11_000_000)
            ],
            rentals=[
                ScheduleERental(
                    name="Office Park", net_rental_cents=1_500_000, is_qbi=True
                )
            ],
        )
    )
    assert out.total_se_earnings_base_cents == 15_000_000
    assert out.total_schedule_1_income_cents == 30_000_000
    assert out.total_qualified_business_income_cents == 28_000_000
    assert len(out.qbi_components) == 5
    sources = sorted(c.source for c in out.qbi_components)
    assert sources == [
        "partnership_k1",
        "partnership_k1",
        "s_corp_k1",
        "schedule_c",
        "schedule_e_rental",
    ]
    # The QBI-flagged rental does NOT emit the default-off assumption.
    assert not any("rental_qbi_default_off" in a for a in out.assumptions)
