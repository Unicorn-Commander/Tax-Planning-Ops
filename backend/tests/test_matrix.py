"""The Matrix (spec §9.8) — the Book's clients × strategy-categories grid.

The grid is a pure roll-up: each cell is the SUM of a category's applied
``ClientStrategy.estimated_savings_cents`` (engine-computed at apply time), so
the math is tested directly against a tiny in-memory fake session — no live DB,
the same approach as tests/test_realized.py's rollup. ``scan_book`` (the
per-client basis) is monkeypatched to a fixed roster, and the strategy
aggregate's ``GROUP BY`` is Postgres's job, so we feed ``execute`` a preset
grouped result and assert the Python summation, the column order, the column
totals, the grand total, and the zero-cell-for-no-strategies behavior.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services import matrix as matrix_svc
from app.services.matrix import build_matrix

WS = uuid4()

# Three clients with stable tax-year ids (strings, as scan_book returns them).
TY_ALICE = str(uuid4())
TY_BOB = str(uuid4())
TY_CARA = str(uuid4())


def _scan_rows() -> list[dict[str, Any]]:
    """What scan_book hands back — already opportunity-ranked (NOT total-tax
    sorted). build_matrix must preserve this order: Alice, Bob, Cara."""
    return [
        {"client_id": "c-alice", "client_name": "Alice", "client_tax_year_id": TY_ALICE},
        {"client_id": "c-bob", "client_name": "Bob", "client_tax_year_id": TY_BOB},
        {"client_id": "c-cara", "client_name": "Cara", "client_tax_year_id": TY_CARA},
    ]


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _MatrixSession:
    """Returns a preset grouped-aggregate result from ``execute`` (the
    ``(client_tax_year_id, category, savings_cents, strategy_count)`` rows the
    GROUP BY would produce). Just enough for ``_category_sums``."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _agg(tax_year_id: str, category: str, savings: int, count: int) -> tuple[Any, ...]:
    # Mirrors the SELECT shape: client_tax_year_id, category, sum, count.
    return (tax_year_id, category, savings, count)


def _patch_scan(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    async def _fake(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(matrix_svc, "scan_book", _fake)


@pytest.mark.asyncio
async def test_cells_are_per_category_sums(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scan(monkeypatch, _scan_rows())
    # The SELECT's GROUP BY (client_tax_year_id, category) already merges a
    # client's strategies within a category, so each (client, category) appears
    # as ONE pre-summed row. Alice: Retirement (2 strategies → 150k) + Charitable
    # (2 → 30k); Bob: one Entity (200k); Cara: none (must still appear, all zeros).
    db = _MatrixSession([
        _agg(TY_ALICE, "Retirement", 150_000, 2),
        _agg(TY_ALICE, "Charitable", 30_000, 2),
        _agg(TY_BOB, "Entity", 200_000, 1),
    ])
    out = await build_matrix(db, workspace_id=WS)

    by_name = {r["client_name"]: r for r in out["rows"]}
    cats = out["categories"]

    def cell(client: str, category: str) -> dict[str, Any]:
        idx = cats.index(category)
        return by_name[client]["cells"][idx]

    # The cell is exactly the engine-summed estimate for that (client, category).
    assert cell("Alice", "Retirement") == {
        "category": "Retirement", "savings_cents": 150_000, "strategy_count": 2,
    }
    assert cell("Alice", "Charitable")["savings_cents"] == 30_000
    assert cell("Alice", "Entity")["savings_cents"] == 0  # no strategy → zero cell
    assert cell("Bob", "Entity")["savings_cents"] == 200_000
    assert by_name["Alice"]["total_savings_cents"] == 180_000
    assert by_name["Bob"]["total_savings_cents"] == 200_000


@pytest.mark.asyncio
async def test_categories_union_is_ordered_by_total_desc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scan(monkeypatch, _scan_rows())
    db = _MatrixSession([
        _agg(TY_ALICE, "Charitable", 30_000, 1),
        _agg(TY_ALICE, "Retirement", 150_000, 1),
        _agg(TY_BOB, "Entity", 200_000, 1),
    ])
    out = await build_matrix(db, workspace_id=WS)
    # Entity (200k) > Retirement (150k) > Charitable (30k).
    assert out["categories"] == ["Entity", "Retirement", "Charitable"]
    # Every row's cells line up positionally with the category order.
    for row in out["rows"]:
        assert [c["category"] for c in row["cells"]] == out["categories"]


@pytest.mark.asyncio
async def test_categories_tie_broken_alphabetically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scan(monkeypatch, _scan_rows())
    db = _MatrixSession([
        _agg(TY_ALICE, "Zeta", 100_000, 1),
        _agg(TY_BOB, "Alpha", 100_000, 1),  # same total as Zeta → Alpha first
    ])
    out = await build_matrix(db, workspace_id=WS)
    assert out["categories"] == ["Alpha", "Zeta"]


@pytest.mark.asyncio
async def test_column_totals_and_grand_total(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scan(monkeypatch, _scan_rows())
    db = _MatrixSession([
        _agg(TY_ALICE, "Retirement", 100_000, 1),
        _agg(TY_BOB, "Retirement", 60_000, 1),
        _agg(TY_ALICE, "Charitable", 40_000, 2),
    ])
    out = await build_matrix(db, workspace_id=WS)

    totals = {c["category"]: c for c in out["column_totals"]}
    assert totals["Retirement"]["savings_cents"] == 160_000
    assert totals["Retirement"]["strategy_count"] == 2
    assert totals["Charitable"]["savings_cents"] == 40_000
    assert totals["Charitable"]["strategy_count"] == 2
    # column_totals align positionally with categories.
    assert [c["category"] for c in out["column_totals"]] == out["categories"]
    # Grand total = every cell = sum of column totals = sum of row totals.
    assert out["grand_total_cents"] == 200_000
    assert out["grand_total_cents"] == sum(c["savings_cents"] for c in out["column_totals"])
    assert out["grand_total_cents"] == sum(r["total_savings_cents"] for r in out["rows"])


@pytest.mark.asyncio
async def test_client_with_no_strategies_appears_with_zero_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scan(monkeypatch, _scan_rows())
    # Only Alice has a strategy; Bob and Cara have none.
    db = _MatrixSession([_agg(TY_ALICE, "Retirement", 100_000, 1)])
    out = await build_matrix(db, workspace_id=WS)

    names = [r["client_name"] for r in out["rows"]]
    assert names == ["Alice", "Bob", "Cara"]  # scan order preserved, all present

    by_name = {r["client_name"]: r for r in out["rows"]}
    # Bob/Cara: one zero cell per category, zero total.
    for name in ("Bob", "Cara"):
        assert by_name[name]["total_savings_cents"] == 0
        assert all(c["savings_cents"] == 0 and c["strategy_count"] == 0
                   for c in by_name[name]["cells"])
        assert len(by_name[name]["cells"]) == len(out["categories"])


@pytest.mark.asyncio
async def test_empty_book_yields_empty_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scan(monkeypatch, [])
    # No clients → no DB query needed, but the session must be safe to pass.
    out = await build_matrix(_MatrixSession([]), workspace_id=WS)
    assert out["categories"] == []
    assert out["rows"] == []
    assert out["column_totals"] == []
    assert out["grand_total_cents"] == 0
