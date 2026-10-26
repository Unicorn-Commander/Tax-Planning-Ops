"""Realized reconciliation — the renewal number (spec §9.7).

Records what a planned strategy ACTUALLY delivered against the plan estimate.
The planned figure is locked from the strategy's ``estimated_savings_cents`` (or
an explicit advisor input) at reconciliation time — never fabricated here; the
realized figure is operator-supplied. ``workspace_rollup`` sums planned vs.
realized across the firm into the Book's "realized counter" (mirrors the
cross-client aggregate shape of ``book_scan.scan_book``). Money is integer cents.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.implementation import RealizedOutcome
from app.models.strategy import ClientStrategy
from app.models.tax_year import ClientTaxYear
from app.schemas.realized import RealizeIn
from app.services.audit import append_audit_event


async def list_realized(
    db: AsyncSession, *, client_tax_year_id: UUID
) -> list[RealizedOutcome]:
    """Reconciled outcomes for a plan year, newest first. RLS scopes to the
    workspace; we filter to the plan year and drop soft-deleted rows."""
    rows = await db.scalars(
        select(RealizedOutcome)
        .where(
            RealizedOutcome.client_tax_year_id == client_tax_year_id,
            RealizedOutcome.deleted_at.is_(None),
        )
        .order_by(RealizedOutcome.created_at.desc())
    )
    return list(rows.all())


async def reconcile(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    client_tax_year_id: UUID,
    payload: RealizeIn,
) -> RealizedOutcome:
    """Reconcile an outcome against ``client_tax_year_id`` (the plan year).

    Locks ``planned_savings_cents``: the explicit input wins; otherwise it's
    pulled from the linked strategy's ``estimated_savings_cents`` (the strategy
    must belong to this tax year); otherwise it's required. The realized figures
    are taken verbatim from the operator. Stamps ``reconciled_by``/
    ``reconciled_at`` and appends an ``outcome.reconciled`` audit event.

    Raises ``LookupError`` if the plan year doesn't exist (or isn't visible to
    this workspace under RLS); ``ValueError`` on a planned figure that can't be
    resolved or a strategy that doesn't belong to the year.
    """
    tax_year = await db.get(ClientTaxYear, client_tax_year_id)
    if tax_year is None:
        raise LookupError("tax year not found")

    # Resolve the PLANNED figure to measure against — explicit input, else the
    # strategy estimate, else error. Never invented.
    planned_savings_cents = payload.planned_savings_cents
    if planned_savings_cents is None:
        if payload.client_strategy_id is not None:
            strategy = await db.get(ClientStrategy, payload.client_strategy_id)
            if strategy is None or strategy.client_tax_year_id != client_tax_year_id:
                raise ValueError("strategy does not belong to this tax year")
            planned_savings_cents = strategy.estimated_savings_cents
        else:
            raise ValueError("planned_savings_cents required")

    outcome = RealizedOutcome(
        workspace_id=workspace_id,
        client_tax_year_id=client_tax_year_id,
        client_strategy_id=payload.client_strategy_id,
        realized_tax_year=payload.realized_tax_year,
        planned_savings_cents=planned_savings_cents,
        realized_savings_cents=payload.realized_savings_cents,
        realized_amount_cents=payload.realized_amount_cents,
        basis=payload.basis,
        source_ref=payload.source_ref,
        source_detail=payload.source_detail,
        reconciled_by=actor_uc_uid,
        reconciled_at=datetime.now(UTC),
        note=payload.note,
    )
    db.add(outcome)
    await db.flush()

    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="outcome.reconciled",
        aggregate_type="realized_outcome",
        aggregate_id=outcome.id,
        payload={
            "client_tax_year_id": str(client_tax_year_id),
            "client_strategy_id": (
                str(payload.client_strategy_id) if payload.client_strategy_id else None
            ),
            "planned_savings_cents": planned_savings_cents,
            "realized_savings_cents": payload.realized_savings_cents,
            "basis": payload.basis,
        },
    )

    await db.refresh(outcome)
    return outcome


async def workspace_rollup(db: AsyncSession, *, workspace_id: UUID) -> dict[str, Any]:
    """The Book's realized counter: planned vs. realized across every reconciled
    outcome in the workspace (RLS-scoped), grouped by client-tax-year and joined
    to the client for the breakdown. Returns the ``RealizedRollupOut`` shape.

    ``realized_savings_cents`` is nullable (an outcome can be recorded before the
    actual lands), so realized sums coalesce a missing actual to 0 — those rows
    contribute their planned amount but no realized amount yet.
    """
    realized_sum = func.coalesce(func.sum(RealizedOutcome.realized_savings_cents), 0)
    result = await db.execute(
        select(
            Client.id,
            Client.display_name,
            ClientTaxYear.id,
            ClientTaxYear.tax_year,
            func.coalesce(func.sum(RealizedOutcome.planned_savings_cents), 0),
            realized_sum,
            func.count(RealizedOutcome.id),
        )
        .join(ClientTaxYear, RealizedOutcome.client_tax_year_id == ClientTaxYear.id)
        .join(Client, ClientTaxYear.client_id == Client.id)
        .where(RealizedOutcome.deleted_at.is_(None))
        .group_by(Client.id, Client.display_name, ClientTaxYear.id, ClientTaxYear.tax_year)
        .order_by(Client.display_name, ClientTaxYear.tax_year)
    )

    clients: list[dict[str, Any]] = []
    total_planned = 0
    total_realized = 0
    for client_id, client_name, tax_year_id, tax_year, planned, realized, count in result.all():
        planned = int(planned if planned is not None else 0)
        realized = int(realized if realized is not None else 0)
        total_planned += planned
        total_realized += realized
        clients.append(
            {
                "client_id": client_id,
                "client_name": client_name,
                "client_tax_year_id": tax_year_id,
                "tax_year": tax_year,
                "planned_cents": planned,
                "realized_cents": realized,
                "variance_cents": realized - planned,
                "outcome_count": int(count),
            }
        )

    pct = (total_realized / total_planned * 100.0) if total_planned else 0.0
    return {
        "total_planned_cents": total_planned,
        "total_realized_cents": total_realized,
        "total_variance_cents": total_realized - total_planned,
        "realized_pct": f"{pct:.1f}%",
        "clients": clients,
    }
