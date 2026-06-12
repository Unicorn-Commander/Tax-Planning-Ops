"""Business-entity intake + multi-entity aggregation.

CRUD for the pass-through interests attached to a client tax year, plus
`aggregate_business` which maps the stored rows onto the passthrough engine and
runs SE tax + the multi-business §199A aggregate — turning entered K-1s /
Schedule C / rentals into the figures a 1040 needs (SE tax, ½ SE deduction,
Schedule-1 income, QBI deduction).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.engine_configs import ty2025_corporate_config, ty2025_qbi_config, ty2025_se_tax_config
from app.engines.corporate import CorporateTaxInput, calculate_corporate_tax
from app.engines.passthrough import (
    PartnershipK1Entity,
    PassthroughInput,
    ScheduleCEntity,
    ScheduleERental,
    SCorpK1Entity,
    aggregate_passthrough,
)
from app.engines.qbi import QBIBusiness, calculate_qbi_aggregate
from app.engines.se_tax import SETaxInput, calculate_se_tax
from app.integrations.accounting_ops import fetch_pl
from app.models.entity import BusinessEntity
from app.schemas.entity import BusinessEntityIn
from app.services.audit import append_audit_event


async def list_entities(
    db: AsyncSession, *, client_tax_year_id: UUID
) -> list[BusinessEntity]:
    result = await db.execute(
        select(BusinessEntity)
        .where(BusinessEntity.client_tax_year_id == client_tax_year_id)
        .order_by(BusinessEntity.created_at)
    )
    return list(result.scalars().all())


async def create_entity(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    client_tax_year_id: UUID,
    payload: BusinessEntityIn,
) -> BusinessEntity:
    entity = BusinessEntity(
        workspace_id=workspace_id,
        client_tax_year_id=client_tax_year_id,
        **payload.model_dump(),
    )
    db.add(entity)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="business_entity_created",
        aggregate_type="business_entity",
        aggregate_id=entity.id,
        payload=payload.model_dump(mode="json"),
    )
    return entity


async def delete_entity(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    entity_id: UUID,
) -> None:
    entity = await db.get(BusinessEntity, entity_id)
    if entity is None:
        raise LookupError("business entity not found")
    await db.delete(entity)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="business_entity_deleted",
        aggregate_type="business_entity",
        aggregate_id=entity_id,
        payload={},
    )


async def sync_entity_from_accounting_ops(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    entity_id: UUID,
    settings: Settings,
) -> dict[str, Any]:
    """Pull the linked Accounting-Ops workspace's P&L net income into the
    entity's `amount_cents`. Raises LookupError if the entity is missing,
    ValueError if it isn't linked, and AccountingOps* errors on the AO call."""
    entity = await db.get(BusinessEntity, entity_id)
    if entity is None:
        raise LookupError("business entity not found")
    if not entity.accounting_ops_workspace_id:
        raise ValueError("entity is not linked to an Accounting-Ops workspace")

    summary = await fetch_pl(entity.accounting_ops_workspace_id, settings)
    previous = entity.amount_cents
    entity.amount_cents = summary.net_income_cents
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="business_entity_synced_accounting_ops",
        aggregate_type="business_entity",
        aggregate_id=entity.id,
        payload={
            "accounting_ops_workspace_id": entity.accounting_ops_workspace_id,
            "previous_amount_cents": previous,
            "amount_cents": summary.net_income_cents,
            "period": summary.period,
        },
    )
    return {
        "entity_id": str(entity.id),
        "accounting_ops_workspace_id": entity.accounting_ops_workspace_id,
        "previous_amount_cents": previous,
        "amount_cents": summary.net_income_cents,
        "period": summary.period,
    }


def _to_passthrough_input(entities: list[BusinessEntity]) -> PassthroughInput:
    schedule_c: list[ScheduleCEntity] = []
    partnerships: list[PartnershipK1Entity] = []
    s_corps: list[SCorpK1Entity] = []
    rentals: list[ScheduleERental] = []
    for e in entities:
        if e.kind == "schedule_c":
            schedule_c.append(
                ScheduleCEntity(
                    name=e.name, net_profit_cents=e.amount_cents, is_sstb=e.is_sstb,
                    w2_wages_paid_cents=e.w2_wages_paid_cents, ubia_cents=e.ubia_cents,
                )
            )
        elif e.kind == "partnership_k1":
            partnerships.append(
                PartnershipK1Entity(
                    name=e.name, ordinary_income_cents=e.amount_cents,
                    is_general_partner=e.is_general_partner, is_sstb=e.is_sstb,
                    w2_wages_paid_cents=e.w2_wages_paid_cents, ubia_cents=e.ubia_cents,
                    guaranteed_payments_cents=e.guaranteed_payments_cents,
                )
            )
        elif e.kind == "s_corp_k1":
            s_corps.append(
                SCorpK1Entity(
                    name=e.name, ordinary_income_cents=e.amount_cents, is_sstb=e.is_sstb,
                    w2_wages_paid_cents=e.w2_wages_paid_cents, ubia_cents=e.ubia_cents,
                    shareholder_w2_wages_cents=e.shareholder_w2_wages_cents,
                )
            )
        elif e.kind == "schedule_e":
            rentals.append(
                ScheduleERental(
                    name=e.name, net_rental_cents=e.amount_cents, is_qbi=e.is_qbi
                )
            )
    return PassthroughInput(
        schedule_c=schedule_c, partnerships=partnerships, s_corps=s_corps, rentals=rentals
    )


class BusinessAggregation(BaseModel):
    """Everything stored business entities contribute to the owner's return.

    Passthroughs feed SE base / Schedule-1 / QBI; a C-corp instead pays its OWN
    tax (`corporate_tax_cents`) and pushes the owner's salary to 1040 wages and
    its dividends to qualified dividends (the double tax)."""

    se_base_cents: int = 0
    schedule_1_cents: int = 0
    qbi_businesses: list[QBIBusiness] = []
    owner_wages_add_cents: int = 0  # C-corp salaries → 1040 wages
    owner_qualified_dividends_cents: int = 0  # C-corp dividends → 1040 qual div
    corporate_tax_cents: int = 0
    has_c_corp: bool = False


def aggregate_for_comprehensive(entities: list[BusinessEntity]) -> BusinessAggregation:
    if not entities:
        return BusinessAggregation()
    pt = aggregate_passthrough(_to_passthrough_input(entities))
    agg = BusinessAggregation(
        se_base_cents=pt.total_se_earnings_base_cents,
        schedule_1_cents=pt.total_schedule_1_income_cents,
        qbi_businesses=[
            QBIBusiness(
                name=c.name, qualified_business_income_cents=c.qbi_cents,
                w2_wages_cents=c.w2_wages_cents, ubia_cents=c.ubia_cents, is_sstb=c.is_sstb,
            )
            for c in pt.qbi_components
        ],
    )
    cfg = ty2025_corporate_config()
    for e in entities:
        if e.kind != "c_corp":
            continue
        agg.has_c_corp = True
        agg.owner_wages_add_cents += e.shareholder_w2_wages_cents
        agg.owner_qualified_dividends_cents += e.dividends_cents
        corp = calculate_corporate_tax(
            CorporateTaxInput(
                pre_nol_taxable_income_cents=e.amount_cents,
                nol_available_cents=e.nol_available_cents,
            ),
            cfg,
        )
        agg.corporate_tax_cents += corp.corporate_tax_cents
    return agg


def business_for_comprehensive(
    entities: list[BusinessEntity],
) -> tuple[int, int, list[QBIBusiness]]:
    """Back-compat tuple for the passthrough pieces (SE base, Schedule-1, QBI)."""
    agg = aggregate_for_comprehensive(entities)
    return agg.se_base_cents, agg.schedule_1_cents, agg.qbi_businesses


def aggregate_business(
    entities: list[BusinessEntity],
    *,
    filing_status: str,
    taxable_income_before_qbi_cents: int,
    net_capital_gain_cents: int = 0,
) -> dict[str, Any]:
    """Map stored entities → passthrough → SE tax + multi-business QBI.

    Returns the figures that flow onto the 1040 plus the engine detail. QBI uses
    `taxable_income_before_qbi_cents` (caller supplies it from the federal
    return). Pure compute; no DB access."""
    if not entities:
        return {"available": False, "reason": "no business entities entered"}

    passthrough = aggregate_passthrough(_to_passthrough_input(entities))

    se = calculate_se_tax(
        SETaxInput(net_self_employment_profit_cents=passthrough.total_se_earnings_base_cents),
        ty2025_se_tax_config(),
    )
    qbi = calculate_qbi_aggregate(
        [
            QBIBusiness(
                name=c.name,
                qualified_business_income_cents=c.qbi_cents,
                w2_wages_cents=c.w2_wages_cents,
                ubia_cents=c.ubia_cents,
                is_sstb=c.is_sstb,
            )
            for c in passthrough.qbi_components
        ],
        filing_status=filing_status,  # type: ignore[arg-type]
        taxable_income_before_qbi_cents=taxable_income_before_qbi_cents,
        net_capital_gain_cents=net_capital_gain_cents,
        config=ty2025_qbi_config(),
    )
    agg = aggregate_for_comprehensive(entities)
    return {
        "available": True,
        "schedule_1_income_cents": passthrough.total_schedule_1_income_cents,
        "se_earnings_base_cents": passthrough.total_se_earnings_base_cents,
        "se_tax_cents": se.total_se_tax_cents,
        "half_se_deduction_cents": se.half_se_deduction_cents,
        "qbi_deduction_cents": qbi.allowed_qbi_deduction_cents,
        "qbi_per_business": [
            {"component_cents": r.qbi_component_cents, "regime": r.regime}
            for r in qbi.per_business
        ],
        "has_c_corp": agg.has_c_corp,
        "corporate_tax_cents": agg.corporate_tax_cents,
        "c_corp_owner_wages_cents": agg.owner_wages_add_cents,
        "c_corp_dividends_cents": agg.owner_qualified_dividends_cents,
        "assumptions": passthrough.assumptions,
    }
