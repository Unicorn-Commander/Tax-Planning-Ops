from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.core.config import Settings, get_settings
from app.db.session import get_tenant_db
from app.models.tax_year import ClientTaxYear, ExtractedField, ExtractedReturn
from app.schemas.auth import AuthContext
from app.schemas.extraction import (
    ClientTaxYearCreate,
    ClientTaxYearRead,
    ConfirmReturnResponse,
    CorrectFieldRequest,
    ExtractedFieldRead,
    ExtractedReturnRead,
)
from app.services.extraction import (
    confirm_return,
    correct_field,
    create_tax_year,
    get_extracted_return,
    upload_return_document,
)

router = APIRouter(tags=["returns"])


@router.post("/client-tax-years", response_model=ClientTaxYearRead, status_code=201)
async def post_client_tax_year(
    payload: ClientTaxYearCreate,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClientTaxYear:
    return await create_tax_year(db, ctx.workspace_id, payload)


@router.post(
    "/client-tax-years/{client_tax_year_id}/documents/form-1040",
    response_model=ExtractedReturnRead,
    status_code=201,
)
async def post_form1040_document(
    client_tax_year_id: UUID,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> ExtractedReturn:
    if file.content_type not in {"application/pdf", "application/octet-stream", None}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="PDF required",
        )
    return await upload_return_document(
        db,
        workspace_id=ctx.workspace_id,
        actor_uc_uid=ctx.uc_uid,
        client_tax_year_id=client_tax_year_id,
        upload=file,
        settings=settings,
    )


@router.get("/extracted-returns/{extracted_return_id}", response_model=ExtractedReturnRead)
async def get_return(
    extracted_return_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ExtractedReturn:
    try:
        return await get_extracted_return(db, extracted_return_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/extracted-fields/{field_id}", response_model=ExtractedFieldRead)
async def patch_field(
    field_id: UUID,
    payload: CorrectFieldRequest,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ExtractedField:
    try:
        return await correct_field(db, field_id=field_id, payload=payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/extracted-returns/{extracted_return_id}/confirm",
    response_model=ConfirmReturnResponse,
)
async def post_confirm_return(
    extracted_return_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ConfirmReturnResponse:
    try:
        snapshot = await confirm_return(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            extracted_return_id=extracted_return_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ConfirmReturnResponse(
        extracted_return_id=extracted_return_id,
        snapshot_id=snapshot.id,
        total_tax_cents=snapshot.total_tax_cents,
        effective_rate=str(snapshot.effective_rate),
    )
