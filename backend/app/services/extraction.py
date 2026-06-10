from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.engines.form1040 import Form1040Inputs, calculate_form1040
from app.integrations.garage import put_object
from app.integrations.ocr_qwenvl import extract_1040
from app.models.tax_config import TaxBracketSet
from app.models.tax_year import (
    ClientTaxYear,
    Document,
    ExtractedField,
    ExtractedReturn,
    TaxSituationSnapshot,
)
from app.schemas.extraction import ClientTaxYearCreate, CorrectFieldRequest
from app.services.audit import append_audit_event
from app.services.tax_config import to_engine_config

FIELD_TO_INPUT = {
    "f1040.line1z_wages": "wages_cents",
    "f1040.line2b_taxable_interest": "taxable_interest_cents",
    "f1040.line3a_qualified_div": "qualified_dividends_cents",
    "f1040.line3b_ordinary_div": "ordinary_dividends_cents",
    "f1040.line4b_ira_taxable": "ira_taxable_cents",
    "f1040.line5b_pensions_taxable": "pensions_taxable_cents",
    "f1040.line6b_ss_taxable": "social_security_taxable_cents",
    "f1040.line7_capital_gain": "capital_gain_loss_cents",
    "f1040.line8_sch1_income": "schedule_1_income_cents",
    "f1040.line10_adjustments": "adjustments_cents",
    "f1040.line12_deduction": "itemized_deduction_cents",
    "f1040.line13_qbi": "qbi_deduction_cents",
    "f1040.line25_withholding": "withholding_cents",
    "f1040.line26_est_payments": "estimated_payments_cents",
    "f1040.line11_agi": "reported_agi_cents",
    "f1040.line15_taxable_income": "reported_taxable_income_cents",
    "f1040.line24_total_tax": "reported_total_tax_cents",
}


async def create_tax_year(
    db: AsyncSession,
    workspace_id: UUID,
    payload: ClientTaxYearCreate,
) -> ClientTaxYear:
    tax_year = ClientTaxYear(workspace_id=workspace_id, **payload.model_dump())
    db.add(tax_year)
    await db.flush()
    await db.refresh(tax_year)
    return tax_year


async def upload_return_document(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    client_tax_year_id: UUID,
    upload: UploadFile,
    settings: Settings,
) -> ExtractedReturn:
    blob = await upload.read()
    digest = hashlib.sha256(blob).hexdigest()
    blob_key = f"{workspace_id}/{client_tax_year_id}/source/{digest}.pdf"
    stored = await put_object(
        key=blob_key,
        data=blob,
        content_type=upload.content_type or "application/pdf",
        settings=settings,
    )
    document = Document(
        workspace_id=workspace_id,
        client_tax_year_id=client_tax_year_id,
        kind="form_1040",
        source_blob_key=stored.key,
        original_filename=upload.filename or "return.pdf",
        content_hash=digest,
        status="ocr_running",
    )
    db.add(document)
    extracted = ExtractedReturn(
        workspace_id=workspace_id,
        client_tax_year_id=client_tax_year_id,
        source_blob_key=stored.key,
        form_type="1040",
        extraction_status="pending",
        extraction_raw={},
    )
    db.add(extracted)
    await db.flush()

    ocr_payload = await extract_1040(stored.key, settings)
    if ocr_payload is None:
        document.status = "extracted"
        extracted.extraction_status = "needs_review"
        extracted.extraction_raw = {"degraded": True, "reason": "ocr disabled or unavailable"}
        extracted.overall_confidence = 0.0
    else:
        document.status = "extracted"
        extracted.extraction_status = "needs_review"
        extracted.ocr_job_id = str(ocr_payload.get("job_id") or "")
        extracted.overall_confidence = float(ocr_payload.get("overall_confidence", 0))
        extracted.extraction_raw = ocr_payload
        for field in ocr_payload.get("fields", []):
            db.add(
                ExtractedField(
                    extracted_return_id=extracted.id,
                    field_key=str(field["field_key"]),
                    value_cents=field.get("value_cents"),
                    value_text=field.get("value_text"),
                    confidence=float(field.get("confidence", 0)),
                    status="auto",
                    bbox=field.get("bbox"),
                )
            )
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="return_document_uploaded",
        aggregate_type="extracted_return",
        aggregate_id=extracted.id,
        payload={"blob_key": stored.key, "content_hash": digest, "encrypted": stored.encrypted},
    )
    await db.flush()
    return await get_extracted_return(db, extracted.id)


async def get_extracted_return(db: AsyncSession, extracted_return_id: UUID) -> ExtractedReturn:
    extracted = await db.scalar(
        select(ExtractedReturn)
        .options(selectinload(ExtractedReturn.fields))
        .where(ExtractedReturn.id == extracted_return_id)
    )
    if extracted is None:
        raise LookupError("extracted return not found")
    return extracted


async def correct_field(
    db: AsyncSession,
    *,
    field_id: UUID,
    payload: CorrectFieldRequest,
) -> ExtractedField:
    field = await db.get(ExtractedField, field_id)
    if field is None:
        raise LookupError("field not found")
    field.corrected_value_cents = payload.corrected_value_cents
    if payload.value_text is not None:
        field.value_text = payload.value_text
    field.status = "corrected"
    await db.flush()
    return field


def _inputs_from_fields(tax_year: ClientTaxYear, fields: list[ExtractedField]) -> Form1040Inputs:
    values: dict[str, Any] = {"filing_status": tax_year.filing_status}
    for field in fields:
        target = FIELD_TO_INPUT.get(field.field_key)
        if not target:
            continue
        values[target] = (
            field.corrected_value_cents
            if field.corrected_value_cents is not None
            else field.value_cents
        )
    return Form1040Inputs(**values)


async def confirm_return(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    extracted_return_id: UUID,
) -> TaxSituationSnapshot:
    extracted = await get_extracted_return(db, extracted_return_id)
    tax_year = await db.get(ClientTaxYear, extracted.client_tax_year_id)
    if tax_year is None:
        raise LookupError("tax year not found")
    bracket_set = await db.scalar(
        select(TaxBracketSet)
        .options(selectinload(TaxBracketSet.rows))
        .where(
            TaxBracketSet.workspace_id.is_(None),
            TaxBracketSet.tax_year == tax_year.tax_year,
            TaxBracketSet.jurisdiction == "federal",
            TaxBracketSet.filing_status == tax_year.filing_status,
        )
    )
    if bracket_set is None:
        raise LookupError("tax bracket set not found")

    inputs = _inputs_from_fields(tax_year, extracted.fields)
    result = calculate_form1040(inputs, to_engine_config(bracket_set))
    extracted.extraction_status = "confirmed"
    extracted.confirmed_by = actor_uc_uid
    tax_year.is_locked = True
    for field in extracted.fields:
        if field.status == "auto":
            field.status = "confirmed"
    snapshot = TaxSituationSnapshot(
        workspace_id=workspace_id,
        client_tax_year_id=tax_year.id,
        inputs=inputs.model_dump(),
        assumptions={},
        bracket_set_id=bracket_set.id,
        total_income_cents=result.total_income_cents,
        agi_cents=result.agi_cents,
        taxable_income_cents=result.taxable_income_cents,
        total_tax_cents=result.total_tax_cents,
        marginal_rate=result.marginal_rate,
        effective_rate=result.effective_rate,
        has_manual_override=any(
            field.corrected_value_cents is not None for field in extracted.fields
        ),
    )
    db.add(snapshot)
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="return_confirmed",
        aggregate_type="extracted_return",
        aggregate_id=extracted.id,
        payload={
            "snapshot_id": snapshot.id,
            "total_tax_cents": result.total_tax_cents,
            "reconciliation": [item.model_dump() for item in result.reconciliation],
        },
    )
    await db.flush()
    return snapshot
