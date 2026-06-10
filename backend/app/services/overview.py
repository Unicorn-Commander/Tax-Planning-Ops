from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.strategy import ClientStrategy, StrategyLibrary
from app.models.tax_year import ClientTaxYear, QuarterlyRecord, TaxSituationSnapshot


def _snapshot_dict(s: TaxSituationSnapshot | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "total_income_cents": s.total_income_cents,
        "agi_cents": s.agi_cents,
        "taxable_income_cents": s.taxable_income_cents,
        "total_tax_cents": s.total_tax_cents,
        "marginal_rate": str(s.marginal_rate),
        "effective_rate": str(s.effective_rate),
        "has_manual_override": s.has_manual_override,
        "assumptions": s.assumptions,
    }


async def get_client_overview(db: AsyncSession, client_id: UUID) -> dict[str, Any]:
    client = await db.get(Client, client_id)
    if client is None:
        raise LookupError("client not found")

    years = list(
        (
            await db.execute(
                select(ClientTaxYear)
                .where(ClientTaxYear.client_id == client_id)
                .order_by(ClientTaxYear.tax_year)
            )
        ).scalars().all()
    )

    async def latest_snapshot(year_id: UUID) -> TaxSituationSnapshot | None:
        snap: TaxSituationSnapshot | None = await db.scalar(
            select(TaxSituationSnapshot)
            .where(TaxSituationSnapshot.client_tax_year_id == year_id)
            .order_by(TaxSituationSnapshot.created_at.desc())
        )
        return snap

    year_rows: list[dict[str, Any]] = []
    base_id: UUID | None = None
    plan_id: UUID | None = None
    for y in years:
        if y.role == "base":
            base_id = y.id
        elif y.role == "plan":
            plan_id = y.id
        year_rows.append(
            {
                "id": str(y.id),
                "tax_year": y.tax_year,
                "role": y.role,
                "filing_status": y.filing_status,
                "is_locked": y.is_locked,
                "finalized_at": y.finalized_at.isoformat() if y.finalized_at else None,
                "snapshot": _snapshot_dict(await latest_snapshot(y.id)),
            }
        )

    strategies: list[dict[str, Any]] = []
    quarterly: list[dict[str, Any]] = []
    if plan_id is not None:
        rows = (
            await db.execute(
                select(ClientStrategy, StrategyLibrary)
                .join(StrategyLibrary, StrategyLibrary.id == ClientStrategy.strategy_id)
                .where(ClientStrategy.client_tax_year_id == plan_id)
            )
        ).all()
        for cs, lib in rows:
            strategies.append(
                {
                    "id": str(cs.id),
                    "name": lib.name,
                    "category": lib.category,
                    "client_facing_copy": lib.client_facing_copy,
                    "disposition": cs.disposition,
                    "amount_cents": cs.amount_cents,
                    "estimated_savings_cents": cs.estimated_savings_cents,
                    "effective_rate_used": str(cs.effective_rate_used),
                    "status_flag": cs.status_flag,
                }
            )
        qrows = (
            await db.execute(
                select(QuarterlyRecord)
                .where(QuarterlyRecord.client_tax_year_id == plan_id)
                .order_by(QuarterlyRecord.quarter)
            )
        ).scalars().all()
        for q in qrows:
            quarterly.append(
                {
                    "quarter": q.quarter,
                    "due_date": q.due_date.date().isoformat(),
                    "required_payment_cents": q.required_payment_cents,
                    "payment_made_cents": q.payment_made_cents,
                    "unpaid_rollforward_cents": q.unpaid_rollforward_cents,
                    "safe_harbor_basis": q.safe_harbor_basis,
                    "status": q.status,
                }
            )

    return {
        "client": {
            "id": str(client.id),
            "display_name": client.display_name,
            "filing_status_default": client.filing_status_default,
            "primary_state": client.primary_state,
            "status": client.status,
            "external_ref": client.external_ref,
            "notes": client.notes,
        },
        "years": year_rows,
        "base_year_id": str(base_id) if base_id else None,
        "plan_year_id": str(plan_id) if plan_id else None,
        "strategies": strategies,
        "quarterly": quarterly,
    }
