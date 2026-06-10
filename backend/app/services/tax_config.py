from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.engines.form1040 import AuxiliaryConfig, RateBracket, TaxConfig, validate_brackets
from app.models.tax_config import TaxBracketRow, TaxBracketSet
from app.schemas.tax_config import TaxBracketSetIn
from app.services.audit import append_audit_event


def _auxiliary_from_json(payload: dict[str, Any]) -> AuxiliaryConfig:
    niit = payload.get("niit") or {}
    medicare = payload.get("additional_medicare") or {}
    qbi = payload.get("qbi") or {}
    aux = AuxiliaryConfig(
        ltcg_brackets=[RateBracket(**row) for row in payload.get("ltcg_brackets", [])],
        niit_threshold_cents=niit.get("threshold_cents"),
        niit_rate=Decimal(str(niit.get("rate", "0"))),
        additional_medicare_threshold_cents=medicare.get("threshold_cents"),
        additional_medicare_rate=Decimal(str(medicare.get("rate", "0"))),
        capital_loss_limit_cents=int(payload.get("capital_loss_limit_cents", 0)),
    )
    if qbi.get("limit_rate") is not None:
        aux.qbi_limit_rate = Decimal(str(qbi["limit_rate"]))
    return aux


def to_engine_config(bracket_set: TaxBracketSet) -> TaxConfig:
    return TaxConfig(
        tax_year=bracket_set.tax_year,
        filing_status=bracket_set.filing_status,
        standard_deduction_cents=bracket_set.standard_deduction_cents,
        ordinary_brackets=[
            RateBracket(
                lower_bound_cents=row.lower_bound_cents,
                upper_bound_cents=row.upper_bound_cents,
                rate=row.rate,
            )
            for row in bracket_set.rows
        ],
        auxiliary=_auxiliary_from_json(bracket_set.auxiliary_schedules),
    )


async def resolve_bracket_set(
    db: AsyncSession,
    *,
    tax_year: int,
    filing_status: str,
    jurisdiction: str = "federal",
) -> TaxBracketSet | None:
    """Prefer a firm override (workspace_id set, visible via RLS) over the
    suite-default seed (workspace_id IS NULL). RLS already scopes overrides to
    the caller's workspace, so we order workspace_id NULLS LAST and take the
    first match — the firm row wins when present, else the seed."""
    result = await db.execute(
        select(TaxBracketSet)
        .options(selectinload(TaxBracketSet.rows))
        .where(
            TaxBracketSet.tax_year == tax_year,
            TaxBracketSet.jurisdiction == jurisdiction,
            TaxBracketSet.filing_status == filing_status,
        )
        .order_by(TaxBracketSet.workspace_id.is_(None))
    )
    return result.scalars().first()


async def list_bracket_sets(
    db: AsyncSession, workspace_id: UUID | None = None
) -> list[TaxBracketSet]:
    stmt = select(TaxBracketSet).options(selectinload(TaxBracketSet.rows)).order_by(
        TaxBracketSet.tax_year, TaxBracketSet.filing_status
    )
    if workspace_id is not None:
        stmt = stmt.where(TaxBracketSet.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def upsert_bracket_set(
    db: AsyncSession,
    payload: TaxBracketSetIn,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
) -> TaxBracketSet:
    validation = validate_brackets(
        [
            RateBracket(
                lower_bound_cents=row.lower_bound_cents,
                upper_bound_cents=row.upper_bound_cents,
                rate=row.rate,
            )
            for row in payload.rows
        ]
    )
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    # A firm only ever writes its OWN override (never the suite-default NULL
    # seed, never another tenant's row). Ignore any workspace_id in the body.
    existing = await db.scalar(
        select(TaxBracketSet)
        .options(selectinload(TaxBracketSet.rows))
        .where(
            TaxBracketSet.workspace_id == workspace_id,
            TaxBracketSet.tax_year == payload.tax_year,
            TaxBracketSet.jurisdiction == payload.jurisdiction,
            TaxBracketSet.filing_status == payload.filing_status,
        )
    )
    is_update = existing is not None
    bracket_set = existing or TaxBracketSet()
    bracket_set.workspace_id = workspace_id
    bracket_set.tax_year = payload.tax_year
    bracket_set.jurisdiction = payload.jurisdiction
    bracket_set.filing_status = payload.filing_status
    bracket_set.standard_deduction_cents = payload.standard_deduction_cents
    bracket_set.auxiliary_schedules = payload.auxiliary_schedules
    bracket_set.notes = payload.notes
    db.add(bracket_set)
    await db.flush()
    await db.execute(delete(TaxBracketRow).where(TaxBracketRow.bracket_set_id == bracket_set.id))
    for row in sorted(payload.rows, key=lambda item: item.ordinal):
        db.add(
            TaxBracketRow(
                bracket_set_id=bracket_set.id,
                lower_bound_cents=row.lower_bound_cents,
                upper_bound_cents=row.upper_bound_cents,
                rate=row.rate,
                ordinal=row.ordinal,
            )
        )
    await db.flush()
    await db.refresh(bracket_set, attribute_names=["rows"])
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="tax_bracket_set_updated" if is_update else "tax_bracket_set_created",
        aggregate_type="tax_bracket_set",
        aggregate_id=bracket_set.id,
        payload={
            "tax_year": payload.tax_year,
            "jurisdiction": payload.jurisdiction,
            "filing_status": payload.filing_status,
            "standard_deduction_cents": payload.standard_deduction_cents,
            "row_count": len(payload.rows),
        },
    )
    return bracket_set
