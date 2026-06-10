from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.quarterly import QuarterlyConfig, QuarterlyInput, compute_quarterly
from app.models.tax_year import ClientTaxYear, QuarterlyRecord
from app.schemas.quarterly import ComputeQuarterlyRequest
from app.services.audit import append_audit_event
from app.services.tax_config import resolve_bracket_set


async def compute_quarterly_for_plan(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    plan_tax_year_id: UUID,
    payload: ComputeQuarterlyRequest,
) -> tuple[str, int, list[QuarterlyRecord]]:
    plan_year = await db.get(ClientTaxYear, plan_tax_year_id)
    if plan_year is None or plan_year.role != "plan":
        raise LookupError("plan year not found")
    bracket_set = await resolve_bracket_set(
        db, tax_year=plan_year.tax_year, filing_status=plan_year.filing_status
    )
    if bracket_set is None:
        raise LookupError("tax config not found")
    safe_harbor = (bracket_set.auxiliary_schedules.get("safe_harbor") or {})
    due_dates = bracket_set.auxiliary_schedules.get("quarterly_due_dates") or []
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=payload.projected_current_year_tax_cents,
            prior_year_tax_cents=payload.prior_year_tax_cents,
            prior_year_agi_cents=payload.prior_year_agi_cents,
            annual_withholding_cents=payload.annual_withholding_cents,
            method=payload.method,
            period_income_cents=payload.period_income_cents,
            payments_made_cents=payload.payments_made_cents,
            config=QuarterlyConfig(
                current_year_rate=Decimal(str(safe_harbor["current_year_rate"])),
                prior_year_rate=Decimal(str(safe_harbor["prior_year_rate"])),
                high_agi_prior_year_rate=Decimal(str(safe_harbor["high_agi_prior_year_rate"])),
                high_agi_threshold_cents=int(safe_harbor["high_agi_threshold_cents"]),
                due_dates=[datetime.fromisoformat(item).date() for item in due_dates],
            ),
        )
    )
    await db.execute(
        delete(QuarterlyRecord).where(QuarterlyRecord.client_tax_year_id == plan_year.id)
    )
    records: list[QuarterlyRecord] = []
    ytd_income = 0
    for quarter, item in enumerate(result.quarters, start=1):
        ytd_income += payload.period_income_cents[quarter - 1]
        record = QuarterlyRecord(
            workspace_id=workspace_id,
            client_tax_year_id=plan_year.id,
            quarter=quarter,
            due_date=datetime.combine(item.due_date, datetime.min.time(), tzinfo=UTC),
            period_income_cents=payload.period_income_cents[quarter - 1],
            period_withholding_cents=0,
            ytd_income_cents=ytd_income,
            annualized_income_cents=item.annualized_income_cents,
            required_payment_cents=item.required_payment_cents,
            safe_harbor_basis=result.safe_harbor_basis,
            payment_made_cents=item.payment_made_cents,
            unpaid_rollforward_cents=item.unpaid_rollforward_cents,
            status=item.status,
        )
        db.add(record)
        records.append(record)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="quarterly_computed",
        aggregate_type="client_tax_year",
        aggregate_id=plan_year.id,
        payload={
            "safe_harbor_basis": result.safe_harbor_basis,
            "required_annual_payment_cents": result.required_annual_payment_cents,
        },
    )
    return result.safe_harbor_basis, result.required_annual_payment_cents, records
