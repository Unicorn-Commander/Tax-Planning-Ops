from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.engines.plan_pdf import BrandingPayload, assemble_plan_pdf_payload
from app.integrations.garage import put_object
from app.integrations.pdf_service import payload_hash, render
from app.models.branding import WorkspaceBranding
from app.models.client import Client
from app.models.strategy import ClientStrategy
from app.models.tax_year import ClientTaxYear, PlanDocument, QuarterlyRecord, TaxSituationSnapshot
from app.schemas.pdf import BrandingIn
from app.services.audit import append_audit_event


async def upsert_branding(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    payload: BrandingIn,
) -> WorkspaceBranding:
    branding = await db.scalar(
        select(WorkspaceBranding).where(WorkspaceBranding.workspace_id == workspace_id)
    )
    if branding is None:
        branding = WorkspaceBranding(workspace_id=workspace_id)
    for key, value in payload.model_dump().items():
        setattr(branding, key, value)
    db.add(branding)
    await db.flush()
    return branding


async def generate_plan_pdf(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    plan_tax_year_id: UUID,
    settings: Settings,
) -> PlanDocument:
    plan_year = await db.get(ClientTaxYear, plan_tax_year_id)
    if plan_year is None:
        raise LookupError("plan year not found")
    client = await db.get(Client, plan_year.client_id)
    if client is None:
        raise LookupError("client not found")
    branding = await db.scalar(
        select(WorkspaceBranding).where(WorkspaceBranding.workspace_id == workspace_id)
    )
    if branding is None:
        branding = WorkspaceBranding(workspace_id=workspace_id, firm_name="Tax Planning Firm")
    snapshots = (
        await db.execute(
            select(TaxSituationSnapshot)
            .where(TaxSituationSnapshot.client_tax_year_id == plan_tax_year_id)
            .order_by(TaxSituationSnapshot.created_at.desc())
        )
    ).scalars().all()
    if not snapshots:
        raise LookupError("projection snapshot not found")
    latest = snapshots[0]
    strategies = (
        await db.execute(
            select(ClientStrategy).where(ClientStrategy.client_tax_year_id == plan_year.id)
        )
    ).scalars().all()
    quarterlies = (
        await db.execute(
            select(QuarterlyRecord)
            .where(QuarterlyRecord.client_tax_year_id == plan_year.id)
            .order_by(QuarterlyRecord.quarter)
        )
    ).scalars().all()
    payload = assemble_plan_pdf_payload(
        branding=BrandingPayload(
            firm_name=branding.firm_name or "Tax Planning Firm",
            logo_blob_key=branding.logo_blob_key,
            primary_color=(
                branding.primary_color
                or BrandingPayload.model_fields["primary_color"].default
            ),
            advisor_signature=branding.advisor_signature,
        ),
        client_name=client.display_name,
        tax_year=plan_year.tax_year,
        current=latest.inputs,
        next_year={
            "total_income_cents": latest.total_income_cents,
            "agi_cents": latest.agi_cents,
            "taxable_income_cents": latest.taxable_income_cents,
            "total_tax_cents": latest.total_tax_cents,
            "marginal_rate": str(latest.marginal_rate),
            "effective_rate": str(latest.effective_rate),
        },
        strategies=[
            {
                "strategy_id": str(item.strategy_id),
                "amount_cents": item.amount_cents,
                "estimated_savings_cents": item.estimated_savings_cents,
                "effective_rate_used": str(item.effective_rate_used),
                "status_flag": item.status_flag,
            }
            for item in strategies
        ],
        quarterly=[
            {
                "quarter": item.quarter,
                "due_date": item.due_date.date().isoformat(),
                "required_payment_cents": item.required_payment_cents,
                "safe_harbor_basis": item.safe_harbor_basis,
                "payment_made_cents": item.payment_made_cents,
            }
            for item in quarterlies
        ],
        has_manual_override=latest.has_manual_override,
        bracket_provenance=str(latest.bracket_set_id),
    )
    payload_dict = payload.model_dump(mode="json")
    rendered = await render(payload_dict, settings)
    version = (
        await db.scalar(
            select(func.coalesce(func.max(PlanDocument.version), 0)).where(
                PlanDocument.client_tax_year_id == plan_year.id
            )
        )
        or 0
    ) + 1
    digest = payload_hash(payload_dict)
    key = f"{workspace_id}/{plan_year.id}/plans/v{version}-{digest}.pdf"
    await put_object(key=key, data=rendered, content_type="application/pdf", settings=settings)
    doc = PlanDocument(
        workspace_id=workspace_id,
        client_tax_year_id=plan_year.id,
        kind="client_plan_pdf",
        garage_key=key,
        version=version,
        payload_hash=digest,
    )
    db.add(doc)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="plan_pdf_generated",
        aggregate_type="plan_document",
        aggregate_id=doc.id,
        payload={"garage_key": key, "version": version, "payload_hash": digest},
    )
    return doc
