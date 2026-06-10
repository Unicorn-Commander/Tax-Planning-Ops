from __future__ import annotations

from decimal import Decimal

from app.engines.strategy_roi import StrategyConfig, StrategyROIInput, compute_strategy_roi


def test_amount_times_effective_rate_snapshots_rate() -> None:
    result = compute_strategy_roi(
        StrategyROIInput(
            amount_cents=100_000,
            effective_rate=Decimal("0.250000"),
            strategy=StrategyConfig(name="Test", savings_method="amount_x_effective_rate"),
        )
    )
    assert result.estimated_savings_cents == 25_000
    assert result.effective_rate_used == Decimal("0.250000")
    assert result.rate_basis_used == "effective_rate"


def test_custom_rate_and_cap() -> None:
    result = compute_strategy_roi(
        StrategyROIInput(
            amount_cents=500_000,
            effective_rate=Decimal("0.100000"),
            strategy=StrategyConfig(
                name="Capped",
                savings_method="amount_x_custom_rate",
                custom_rate=Decimal("0.4000"),
                statutory_cap_cents=200_000,
            ),
        )
    )
    assert result.amount_used_cents == 200_000
    assert result.estimated_savings_cents == 80_000
    assert result.cap_applied


def test_applicability_rules_flag_strategy() -> None:
    result = compute_strategy_roi(
        StrategyROIInput(
            amount_cents=100_000,
            effective_rate=Decimal("0.200000"),
            facts={"has_schedule_c": False},
            strategy=StrategyConfig(
                name="Sch C",
                savings_method="amount_x_effective_rate",
                applicability_rules={"requires_schedule_c": True},
            ),
        )
    )
    assert not result.applicable
    assert result.estimated_savings_cents == 0
