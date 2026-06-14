"""Realized reconciliation — the renewal number (spec §9.7).

The variance math and the rollup summation/percentage are pure, so they're
tested directly: ``RealizedOutcomeOut`` computes variance (realized − planned)
in a model_validator, and ``workspace_rollup`` sums planned/realized and guards
the realized-% against a zero denominator. The ``reconcile`` planned-figure
resolution (explicit input vs. locked-from-strategy vs. required — never
fabricated) runs against a tiny in-memory fake session, the same approach as
tests/test_tasks.py, so no DB is touched; the RLS path lives in
tests/test_rls_integration.py's style.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest

from app.models.implementation import RealizedOutcome
from app.models.strategy import ClientStrategy
from app.models.tax_year import ClientTaxYear
from app.schemas.realized import RealizedOutcomeOut, RealizeIn
from app.services.realized import reconcile, workspace_rollup


# --------------------------------------------------------------------------- #
# variance_cents — realized − planned, only once an actual is recorded.
# --------------------------------------------------------------------------- #
def _out(**overrides: Any) -> RealizedOutcomeOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "client_tax_year_id": uuid4(),
        "client_strategy_id": None,
        "realized_tax_year": 2027,
        "planned_savings_cents": 100_000,
        "realized_savings_cents": None,
        "realized_amount_cents": None,
        "basis": "manual",
        "source_ref": None,
        "source_detail": None,
        "reconciled_by": "advisor",
        "reconciled_at": None,
        "note": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return RealizedOutcomeOut(**base)


def test_variance_is_realized_minus_planned() -> None:
    out = _out(planned_savings_cents=100_000, realized_savings_cents=120_000)
    assert out.variance_cents == 20_000


def test_variance_is_negative_when_underdelivered() -> None:
    out = _out(planned_savings_cents=100_000, realized_savings_cents=75_000)
    assert out.variance_cents == -25_000


def test_variance_is_none_until_realized_recorded() -> None:
    out = _out(planned_savings_cents=100_000, realized_savings_cents=None)
    assert out.variance_cents is None


def test_variance_zero_realized_is_full_negative_variance() -> None:
    # A recorded actual of 0 is distinct from "not yet measured" (None).
    out = _out(planned_savings_cents=100_000, realized_savings_cents=0)
    assert out.variance_cents == -100_000


# --------------------------------------------------------------------------- #
# workspace_rollup — summation + realized-% guard, against a fake result set.
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _RollupSession:
    """Returns a preset grouped-aggregate result from ``execute``. Just enough
    for ``workspace_rollup`` — the SQL grouping/coalesce is Postgres's job; here
    we verify the Python summation + percentage on its output."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _row(name: str, planned: int, realized: int, count: int) -> tuple[Any, ...]:
    # (client_id, client_name, client_tax_year_id, tax_year, planned, realized, count)
    return (uuid4(), name, uuid4(), 2026, planned, realized, count)


@pytest.mark.asyncio
async def test_rollup_sums_planned_and_realized_across_rows() -> None:
    db = _RollupSession([
        _row("Alice", planned=100_000, realized=120_000, count=2),
        _row("Bob", planned=50_000, realized=40_000, count=1),
    ])
    out = await workspace_rollup(db, workspace_id=uuid4())
    assert out["total_planned_cents"] == 150_000
    assert out["total_realized_cents"] == 160_000
    assert out["total_variance_cents"] == 10_000
    assert len(out["clients"]) == 2
    # Per-client variance is realized − planned.
    by_name = {c["client_name"]: c for c in out["clients"]}
    assert by_name["Alice"]["variance_cents"] == 20_000
    assert by_name["Bob"]["variance_cents"] == -10_000
    assert by_name["Alice"]["outcome_count"] == 2


@pytest.mark.asyncio
async def test_rollup_realized_pct_guards_zero_planned() -> None:
    # No outcomes at all → no divide-by-zero, "0.0%".
    out = await workspace_rollup(_RollupSession([]), workspace_id=uuid4())
    assert out["total_planned_cents"] == 0
    assert out["realized_pct"] == "0.0%"
    assert out["clients"] == []


@pytest.mark.asyncio
async def test_rollup_realized_pct_is_realized_over_planned() -> None:
    db = _RollupSession([_row("Alice", planned=200_000, realized=150_000, count=1)])
    out = await workspace_rollup(db, workspace_id=uuid4())
    assert out["realized_pct"] == "75.0%"


# --------------------------------------------------------------------------- #
# reconcile — the planned figure is locked, never fabricated.
# --------------------------------------------------------------------------- #
class _ReconcileSession:
    """Minimal async fake: ``get`` returns a preset keyed by model; ``scalar``
    (the audit-chain tip lookup) returns None; ``add``/``flush``/``refresh`` are
    recorded/no-ops. Enough for ``reconcile`` + ``append_audit_event`` with no DB."""

    def __init__(self, *, tax_year: Any, strategy: Any = None) -> None:
        self._by_model = {ClientTaxYear: tax_year, ClientStrategy: strategy}
        self.added: list[Any] = []

    async def get(self, model: Any, _pk: Any) -> Any:
        return self._by_model.get(model)

    async def scalar(self, _stmt: Any) -> Any:
        return None  # no prior audit event

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _tax_year(ty_id: Any) -> ClientTaxYear:
    return ClientTaxYear(
        id=ty_id,
        workspace_id=uuid4(),
        client_id=uuid4(),
        tax_year=2026,
        role="plan",
        filing_status="mfj",
    )


def _strategy(ty_id: Any, *, estimated_savings_cents: int) -> ClientStrategy:
    return ClientStrategy(
        id=uuid4(),
        workspace_id=uuid4(),
        client_tax_year_id=ty_id,
        strategy_id=uuid4(),
        disposition="recommended",
        amount_cents=500_000,
        effective_rate_used=0,
        estimated_savings_cents=estimated_savings_cents,
        status_flag="explore",
    )


@pytest.mark.asyncio
async def test_reconcile_uses_explicit_planned_when_given() -> None:
    ty_id = uuid4()
    db = _ReconcileSession(tax_year=_tax_year(ty_id))
    out = await reconcile(
        db,
        workspace_id=uuid4(),
        actor_uc_uid="advisor",
        client_tax_year_id=ty_id,
        payload=RealizeIn(realized_tax_year=2027, planned_savings_cents=88_000),
    )
    assert out.planned_savings_cents == 88_000
    assert out.reconciled_by == "advisor"
    assert out.reconciled_at is not None
    # A RealizedOutcome + an audit event were staged.
    assert any(isinstance(o, RealizedOutcome) for o in db.added)


@pytest.mark.asyncio
async def test_reconcile_locks_planned_from_strategy_estimate() -> None:
    ty_id = uuid4()
    strategy = _strategy(ty_id, estimated_savings_cents=42_500)
    db = _ReconcileSession(tax_year=_tax_year(ty_id), strategy=strategy)
    out = await reconcile(
        db,
        workspace_id=uuid4(),
        actor_uc_uid="advisor",
        client_tax_year_id=ty_id,
        payload=RealizeIn(realized_tax_year=2027, client_strategy_id=strategy.id),
    )
    # Pulled from the strategy estimate — not fabricated.
    assert out.planned_savings_cents == 42_500


@pytest.mark.asyncio
async def test_reconcile_requires_planned_when_no_strategy() -> None:
    ty_id = uuid4()
    db = _ReconcileSession(tax_year=_tax_year(ty_id))
    with pytest.raises(ValueError, match="planned_savings_cents required"):
        await reconcile(
            db,
            workspace_id=uuid4(),
            actor_uc_uid="advisor",
            client_tax_year_id=ty_id,
            payload=RealizeIn(realized_tax_year=2027),
        )


@pytest.mark.asyncio
async def test_reconcile_rejects_strategy_from_another_tax_year() -> None:
    ty_id = uuid4()
    # Strategy belongs to a DIFFERENT tax year.
    strategy = _strategy(uuid4(), estimated_savings_cents=42_500)
    db = _ReconcileSession(tax_year=_tax_year(ty_id), strategy=strategy)
    with pytest.raises(ValueError, match="does not belong"):
        await reconcile(
            db,
            workspace_id=uuid4(),
            actor_uc_uid="advisor",
            client_tax_year_id=ty_id,
            payload=RealizeIn(realized_tax_year=2027, client_strategy_id=strategy.id),
        )


@pytest.mark.asyncio
async def test_reconcile_missing_tax_year_raises_lookup() -> None:
    db = _ReconcileSession(tax_year=None)
    with pytest.raises(LookupError):
        await reconcile(
            db,
            workspace_id=uuid4(),
            actor_uc_uid="advisor",
            client_tax_year_id=uuid4(),
            payload=RealizeIn(realized_tax_year=2027, planned_savings_cents=1),
        )
