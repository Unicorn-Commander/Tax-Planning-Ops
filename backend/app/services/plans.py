from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.engines.form1040 import Form1040Inputs, Form1040Result
from app.engines.projection import project_tax_situation
from app.models.tax_config import TaxBracketSet
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.schemas.plans import ProjectionSnapshotRead
from app.services.audit import append_audit_event
from app.services.tax_config import to_engine_config


async def _bracket_set(
    db: AsyncSession,
    *,
    tax_year: int,
    filing_status: str,
) -> TaxBracketSet:
    bracket_set = await db.scalar(
        select(TaxBracketSet)
        .options(selectinload(TaxBracketSet.rows))
        .where(
            TaxBracketSet.workspace_id.is_(None),
            TaxBracketSet.tax_year == tax_year,
            TaxBracketSet.jurisdiction == "federal",
            TaxBracketSet.filing_status == filing_status,
        )
    )
    if bracket_set is None:
        raise LookupError("tax bracket set not found")
    return bracket_set


async def _latest_snapshot(db: AsyncSession, tax_year_id: UUID) -> TaxSituationSnapshot:
    snapshot = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    if snapshot is None:
        raise LookupError("snapshot not found")
    return snapshot


def _snapshot_read(
    tax_year: ClientTaxYear,
    snapshot: TaxSituationSnapshot,
    delta_total_tax_cents: int | None = None,
) -> ProjectionSnapshotRead:
    return ProjectionSnapshotRead(
        client_tax_year_id=tax_year.id,
        tax_year=tax_year.tax_year,
        role=tax_year.role,
        inputs=snapshot.inputs,
        assumptions=snapshot.assumptions,
        total_income_cents=snapshot.total_income_cents,
        agi_cents=snapshot.agi_cents,
        taxable_income_cents=snapshot.taxable_income_cents,
        total_tax_cents=snapshot.total_tax_cents,
        marginal_rate=str(snapshot.marginal_rate),
        effective_rate=str(snapshot.effective_rate),
        delta_total_tax_cents=delta_total_tax_cents,
    )


def _merge_assumptions(inputs: dict[str, Any], assumptions: dict[str, Any]) -> dict[str, Any]:
    merged = dict(inputs)
    for key, value in assumptions.items():
        if key.endswith("_delta_cents"):
            target = key.removesuffix("_delta_cents")
            merged[target] = int(merged.get(target, 0) or 0) + int(value)
        else:
            merged[key] = value
    return merged


def _result_from_snapshot(snapshot: TaxSituationSnapshot) -> Form1040Result:
    return Form1040Result(
        total_income_cents=snapshot.total_income_cents,
        agi_cents=snapshot.agi_cents,
        deduction_cents=0,
        qbi_deduction_cents=0,
        taxable_income_cents=snapshot.taxable_income_cents,
        ordinary_tax_cents=0,
        preferential_tax_cents=0,
        niit_cents=0,
        additional_medicare_cents=0,
        nonrefundable_credits_cents=0,
        total_tax_cents=snapshot.total_tax_cents,
        marginal_rate=Decimal(str(snapshot.marginal_rate)),
        effective_rate=Decimal(str(snapshot.effective_rate)),
        balance_due_cents=0,
        reconciliation=[],
        other_taxes={},
    )


async def create_plan_from_base(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    base_tax_year_id: UUID,
    target_tax_year: int,
) -> tuple[ClientTaxYear, TaxSituationSnapshot]:
    base_year = await db.get(ClientTaxYear, base_tax_year_id)
    if base_year is None or not base_year.is_locked:
        raise LookupError("confirmed locked base year not found")
    base_snapshot = await _latest_snapshot(db, base_tax_year_id)
    plan_year = ClientTaxYear(
        workspace_id=workspace_id,
        client_id=base_year.client_id,
        tax_year=target_tax_year,
        role="plan",
        filing_status=base_year.filing_status,
        source_year_id=base_year.id,
        is_locked=False,
    )
    db.add(plan_year)
    await db.flush()
    bracket_set = await _bracket_set(
        db, tax_year=target_tax_year, filing_status=plan_year.filing_status
    )
    inputs = dict(base_snapshot.inputs)
    inputs["filing_status"] = plan_year.filing_status
    projection = project_tax_situation(
        Form1040Inputs(**inputs),
        to_engine_config(bracket_set),
        _result_from_snapshot(base_snapshot),
    )
    result = projection.projected
    snapshot = TaxSituationSnapshot(
        workspace_id=workspace_id,
        client_tax_year_id=plan_year.id,
        inputs=inputs,
        assumptions={},
        bracket_set_id=bracket_set.id,
        total_income_cents=result.total_income_cents,
        agi_cents=result.agi_cents,
        taxable_income_cents=result.taxable_income_cents,
        total_tax_cents=result.total_tax_cents,
        marginal_rate=result.marginal_rate,
        effective_rate=result.effective_rate,
        has_manual_override=False,
    )
    db.add(snapshot)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="tax_plan_created",
        aggregate_type="client_tax_year",
        aggregate_id=plan_year.id,
        payload={"source_year_id": base_tax_year_id, "snapshot_id": snapshot.id},
    )
    return plan_year, snapshot


async def update_plan_assumptions(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    plan_tax_year_id: UUID,
    assumptions: dict[str, Any],
) -> TaxSituationSnapshot:
    plan_year = await db.get(ClientTaxYear, plan_tax_year_id)
    if plan_year is None or plan_year.role != "plan":
        raise LookupError("plan year not found")
    current_snapshot = await _latest_snapshot(db, plan_tax_year_id)
    bracket_set = await _bracket_set(
        db,
        tax_year=plan_year.tax_year,
        filing_status=plan_year.filing_status,
    )
    merged_inputs = _merge_assumptions(current_snapshot.inputs, assumptions)
    projection = project_tax_situation(
        Form1040Inputs(**merged_inputs),
        to_engine_config(bracket_set),
    )
    result = projection.projected
    snapshot = TaxSituationSnapshot(
        workspace_id=workspace_id,
        client_tax_year_id=plan_year.id,
        inputs=merged_inputs,
        assumptions=assumptions,
        bracket_set_id=bracket_set.id,
        total_income_cents=result.total_income_cents,
        agi_cents=result.agi_cents,
        taxable_income_cents=result.taxable_income_cents,
        total_tax_cents=result.total_tax_cents,
        marginal_rate=result.marginal_rate,
        effective_rate=result.effective_rate,
        has_manual_override=True,
    )
    db.add(snapshot)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="scenario_assumptions_updated",
        aggregate_type="client_tax_year",
        aggregate_id=plan_year.id,
        payload={"assumptions": assumptions, "snapshot_id": snapshot.id},
    )
    return snapshot
