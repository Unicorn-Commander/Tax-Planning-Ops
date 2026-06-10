from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.strategy_roi import StrategyConfig, StrategyROIInput, compute_strategy_roi
from app.models.strategy import ClientStrategy, StrategyLibrary
from app.models.tax_year import TaxSituationSnapshot
from app.schemas.strategy import AddClientStrategyRequest, StrategyLibraryIn
from app.services.audit import append_audit_event


async def upsert_strategy_library(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    payload: StrategyLibraryIn,
    strategy_id: UUID | None = None,
) -> StrategyLibrary:
    strategy = await db.get(StrategyLibrary, strategy_id) if strategy_id else StrategyLibrary()
    if strategy is None:
        raise LookupError("strategy not found")
    strategy.workspace_id = workspace_id
    for key, value in payload.model_dump().items():
        setattr(strategy, key, value)
    db.add(strategy)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="strategy_library_upserted",
        aggregate_type="strategy_library",
        aggregate_id=strategy.id,
        payload=payload.model_dump(mode="json"),
    )
    return strategy


async def list_strategy_library(db: AsyncSession, workspace_id: UUID) -> list[StrategyLibrary]:
    result = await db.execute(
        select(StrategyLibrary)
        .where(StrategyLibrary.workspace_id == workspace_id, StrategyLibrary.is_active.is_(True))
        .order_by(StrategyLibrary.sort_order, StrategyLibrary.name)
    )
    return list(result.scalars().all())


async def add_client_strategy(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    client_tax_year_id: UUID,
    payload: AddClientStrategyRequest,
) -> ClientStrategy:
    strategy = await db.get(StrategyLibrary, payload.strategy_id)
    if strategy is None:
        raise LookupError("strategy not found")
    snapshot = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == client_tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    if snapshot is None:
        raise LookupError("snapshot not found")
    roi = compute_strategy_roi(
        StrategyROIInput(
            amount_cents=payload.amount_cents,
            effective_rate=Decimal(str(snapshot.effective_rate)),
            manual_savings_cents=payload.manual_savings_cents,
            facts={
                "agi_cents": snapshot.agi_cents,
                "total_income_cents": snapshot.total_income_cents,
            },
            strategy=StrategyConfig(
                name=strategy.name,
                savings_method=strategy.savings_method,
                custom_rate=strategy.custom_rate,
                statutory_cap_cents=strategy.statutory_cap_cents,
                applicability_rules=strategy.applicability_rules,
            ),
        )
    )
    client_strategy = ClientStrategy(
        workspace_id=workspace_id,
        client_tax_year_id=client_tax_year_id,
        strategy_id=strategy.id,
        disposition=payload.disposition,
        amount_cents=roi.amount_used_cents,
        effective_rate_used=roi.effective_rate_used,
        estimated_savings_cents=roi.estimated_savings_cents,
        status_flag=payload.status_flag,
        advisor_note=payload.advisor_note,
    )
    db.add(client_strategy)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="client_strategy_added",
        aggregate_type="client_strategy",
        aggregate_id=client_strategy.id,
        payload={
            "strategy_id": strategy.id,
            "estimated_savings_cents": roi.estimated_savings_cents,
            "rate_basis_used": roi.rate_basis_used,
            "cap_applied": roi.cap_applied,
            "applicable": roi.applicable,
            "reason": roi.reason,
        },
    )
    return client_strategy
