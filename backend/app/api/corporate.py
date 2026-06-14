from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.corporate import CorporateAnalysis
from app.services.corporate_analysis import get_corporate_analysis

router = APIRouter(prefix="/clients/tax-years", tags=["corporate-analysis"])


@router.get(
    "/{tax_year_id}/corporate-analysis",
    response_model=CorporateAnalysis,
)
async def corporate_analysis(
    tax_year_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    """Integrated Form 1120 planning picture for the C-corp(s) on a tax year:
    the corporate return (federal 21% + state, after the §172 NOL), the
    accumulated-earnings-tax watch, the double tax at the current salary/dividend
    split with the retained-earnings alternative, and the salary-vs-dividend
    optimization that minimises the combined corporate + owner tax. Every figure
    is engine-computed. Returns `available: false` (200) when there is no C-corp
    on the year; 404 when the tax year, snapshot, or bracket set is missing."""
    try:
        return await get_corporate_analysis(db, tax_year_id=tax_year_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
