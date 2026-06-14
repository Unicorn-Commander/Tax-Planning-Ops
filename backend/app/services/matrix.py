"""The Matrix (spec §9.8) — scan-book, extended per strategy category.

The Book renders a clients × strategy-categories grid with a dollar figure in
each cell. Today the frontend derives that from the opportunity scan; this
service makes it a real backend aggregate.

Cell $ = the SUM of that category's applied ``ClientStrategy.estimated_savings_cents``
for the client — figures the strategy-ROI engine already computed when each
strategy was applied. This module never re-estimates a saving and never
fabricates one: an empty cell is genuinely 0 (no strategy in that category).

The per-client basis is ``scan_book``: it picks one tax year per client and
returns them in opportunity-ranked order. We keep that order and that exact
tax-year choice (we DO NOT re-sort clients by total tax — a known v1 bug),
then roll the strategies applied to those tax years up by category.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import ClientStrategy, StrategyLibrary
from app.services.book_scan import scan_book


async def _category_sums(
    db: AsyncSession, tax_year_ids: list[UUID]
) -> dict[tuple[str, str], tuple[int, int]]:
    """Grouped aggregate: for the given client-tax-year ids, sum every applied
    strategy's engine-computed ``estimated_savings_cents`` and count the
    strategies, keyed by ``(client_tax_year_id, category)``.

    RLS-scoped via the session GUC; we additionally constrain to the scan's
    tax-year ids so the grid lines up 1:1 with the Book's rows. Returns
    ``{(tax_year_id_str, category): (savings_cents, strategy_count)}``.
    """
    if not tax_year_ids:
        return {}
    result = await db.execute(
        select(
            ClientStrategy.client_tax_year_id,
            StrategyLibrary.category,
            func.coalesce(func.sum(ClientStrategy.estimated_savings_cents), 0),
            func.count(ClientStrategy.id),
        )
        .join(StrategyLibrary, ClientStrategy.strategy_id == StrategyLibrary.id)
        .where(ClientStrategy.client_tax_year_id.in_(tax_year_ids))
        .group_by(ClientStrategy.client_tax_year_id, StrategyLibrary.category)
    )
    sums: dict[tuple[str, str], tuple[int, int]] = {}
    for tax_year_id, category, savings, count in result.all():
        sums[(str(tax_year_id), category)] = (int(savings), int(count))
    return sums


def _ordered_categories(sums: dict[tuple[str, str], tuple[int, int]]) -> list[str]:
    """Stable column order: by total savings across the book (desc), tie-broken
    alphabetically so the column set is deterministic run-to-run."""
    totals: dict[str, int] = {}
    for (_tax_year_id, category), (savings, _count) in sums.items():
        totals[category] = totals.get(category, 0) + savings
    return sorted(totals, key=lambda c: (-totals[c], c))


async def build_matrix(
    db: AsyncSession, *, workspace_id: UUID, limit: int = 50
) -> dict[str, Any]:
    """Build the Book matrix: rows = clients (scan_book order, one tax year each),
    columns = strategy categories, cell = sum of that category's engine-computed
    strategy estimates for the client (0 where none).

    Every dollar is sourced from ``ClientStrategy.estimated_savings_cents`` (the
    strategy-ROI engine's output at apply time); this function only sums and
    arranges them. Clients with no applied strategies still appear as a full row
    of zero cells. Returns the ``MatrixOut`` shape.
    """
    clients = await scan_book(db, workspace_id, limit)
    tax_year_ids = [UUID(c["client_tax_year_id"]) for c in clients]
    sums = await _category_sums(db, tax_year_ids)

    categories = _ordered_categories(sums)

    rows: list[dict[str, Any]] = []
    column_totals_cents = dict.fromkeys(categories, 0)
    column_totals_count = dict.fromkeys(categories, 0)
    grand_total = 0

    for client in clients:
        tax_year_id = client["client_tax_year_id"]
        cells: list[dict[str, Any]] = []
        row_total = 0
        for category in categories:
            savings, count = sums.get((tax_year_id, category), (0, 0))
            cells.append(
                {"category": category, "savings_cents": savings, "strategy_count": count}
            )
            row_total += savings
            column_totals_cents[category] += savings
            column_totals_count[category] += count
        grand_total += row_total
        rows.append(
            {
                "client_id": client["client_id"],
                "client_name": client["client_name"],
                "client_tax_year_id": tax_year_id,
                "total_savings_cents": row_total,
                "cells": cells,
            }
        )

    column_totals = [
        {
            "category": category,
            "savings_cents": column_totals_cents[category],
            "strategy_count": column_totals_count[category],
        }
        for category in categories
    ]

    return {
        "categories": categories,
        "rows": rows,
        "column_totals": column_totals,
        "grand_total_cents": grand_total,
    }
