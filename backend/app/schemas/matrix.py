"""The Matrix (spec §9.8) — the Book's clients × strategy-categories grid.

Each cell holds the engine-computed savings for one client in one strategy
category: the SUM of that category's applied ``ClientStrategy.estimated_savings_cents``
(already computed by the strategy-ROI engine at apply time). The grid is a pure
roll-up of those stored estimates — nothing here re-estimates or fabricates a
figure, and rows are NOT re-ranked by total tax (a known v1 bug); they inherit
the opportunity-ranked order of ``scan_book``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MatrixCell(BaseModel):
    """One client × category intersection (or, in ``column_totals``, a whole
    column). ``savings_cents`` is the sum of the engine's per-strategy estimates;
    ``strategy_count`` is how many applied strategies rolled into it (0 = none)."""

    category: str
    savings_cents: int = 0
    strategy_count: int = 0


class MatrixRow(BaseModel):
    """A client's row: one cell per category column (0 where the client has no
    strategy in that category), plus the client's total across all columns."""

    client_id: str
    client_name: str
    client_tax_year_id: str
    total_savings_cents: int = 0
    cells: list[MatrixCell] = Field(default_factory=list)


class MatrixOut(BaseModel):
    """The full grid. ``categories`` is the stable column order shared by every
    row's ``cells`` and by ``column_totals`` (positionally aligned). ``grand_total_cents``
    is the sum of every cell = the workspace's total planned strategy savings."""

    categories: list[str] = Field(default_factory=list)
    rows: list[MatrixRow] = Field(default_factory=list)
    column_totals: list[MatrixCell] = Field(default_factory=list)
    grand_total_cents: int = 0
