from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tax_config import TaxBracketSet
from app.models.tax_year import ClientTaxYear
from app.services.audit import append_audit_event, verify_audit_chain


def bracket_snapshot(bracket_set: TaxBracketSet) -> dict[str, Any]:
    return {
        "id": str(bracket_set.id),
        "tax_year": bracket_set.tax_year,
        "jurisdiction": bracket_set.jurisdiction,
        "filing_status": bracket_set.filing_status,
        "standard_deduction_cents": bracket_set.standard_deduction_cents,
        "auxiliary_schedules": bracket_set.auxiliary_schedules,
        "rows": [
            {
                "lower_bound_cents": row.lower_bound_cents,
                "upper_bound_cents": row.upper_bound_cents,
                "rate": str(row.rate),
                "ordinal": row.ordinal,
            }
            for row in bracket_set.rows
        ],
    }


async def finalize_plan(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    plan_tax_year_id: UUID,
) -> ClientTaxYear:
    plan = await db.get(ClientTaxYear, plan_tax_year_id)
    if plan is None or plan.role != "plan":
        raise LookupError("plan year not found")
    bracket_set = await db.scalar(
        select(TaxBracketSet)
        .options(selectinload(TaxBracketSet.rows))
        .where(
            TaxBracketSet.workspace_id.is_(None),
            TaxBracketSet.tax_year == plan.tax_year,
            TaxBracketSet.jurisdiction == "federal",
            TaxBracketSet.filing_status == plan.filing_status,
        )
    )
    if bracket_set is None:
        raise LookupError("tax bracket set not found")
    plan.is_locked = True
    plan.finalized_at = datetime.now(UTC)
    plan.pinned_bracket_config = bracket_snapshot(bracket_set)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="plan_finalized",
        aggregate_type="client_tax_year",
        aggregate_id=plan.id,
        payload={"pinned_bracket_set_id": str(bracket_set.id), "finalized_at": plan.finalized_at},
    )
    return plan


async def verify_workspace_audit_chain(db: AsyncSession, workspace_id: UUID) -> bool:
    return await verify_audit_chain(db, workspace_id)
