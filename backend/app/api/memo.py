from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.core.config import Settings, get_settings
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.memo import (
    MemoOut,
    MemoSaveIn,
    MemoState,
    PendingMemoOut,
    RedlineOut,
    StrategistRunOut,
)
from app.services.memo import (
    get_memo_state,
    list_pending_memos,
    persist_strategist_run,
    redline,
    save_memo_draft,
    sign_memo,
)

router = APIRouter(tags=["memo"])


@router.post("/clients/tax-years/{tax_year_id}/strategist/run")
async def post_strategist_run(
    tax_year_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Run the AI strategist, persist the immutable run, and seed/refresh the
    working draft memo. Returns the run plus the resulting memo state. Every
    figure is engine-computed; the model only narrates."""
    try:
        run = await persist_strategist_run(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            tax_year_id=tax_year_id,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    state = await get_memo_state(db, tax_year_id=tax_year_id)
    return {
        "run": StrategistRunOut.model_validate(run),
        "memo_state": MemoState.model_validate(state),
    }


@router.get("/clients/tax-years/{tax_year_id}/memo", response_model=MemoState)
async def get_memo(
    tax_year_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> MemoState:
    """The working/latest memo, the version history, and the run it was built
    from. RLS scopes everything to the workspace."""
    return MemoState.model_validate(await get_memo_state(db, tax_year_id=tax_year_id))


@router.put("/clients/tax-years/{tax_year_id}/memo", response_model=MemoOut)
async def put_memo(
    tax_year_id: UUID,
    payload: MemoSaveIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> MemoOut:
    """Save the advisor's working draft. Edits the open draft in place, or opens
    a fresh draft if the latest version is already signed."""
    memo = await save_memo_draft(
        db, workspace_id=ctx.workspace_id, tax_year_id=tax_year_id, body_md=payload.body_md
    )
    return MemoOut.model_validate(memo)


@router.post("/memos/{memo_id}/sign", response_model=MemoOut)
async def post_sign_memo(
    memo_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> MemoOut:
    """Seal a draft memo: snapshot its content hash and append a tamper-evident
    ``memo.signed`` event to the audit hash-chain."""
    try:
        memo = await sign_memo(
            db, workspace_id=ctx.workspace_id, actor_uc_uid=ctx.uc_uid, memo_id=memo_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MemoOut.model_validate(memo)


@router.get("/memos/pending", response_model=list[PendingMemoOut])
async def get_pending_memos(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[PendingMemoOut]:
    """The sign-off queue: every draft memo in the workspace, newest first."""
    rows = await list_pending_memos(db, workspace_id=ctx.workspace_id)
    return [PendingMemoOut.model_validate(row) for row in rows]


@router.get("/memos/{memo_id}/redline", response_model=RedlineOut)
async def get_memo_redline(
    memo_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> RedlineOut:
    """Diff this memo (narrative + engine findings) against the prior signed
    version it supersedes. The base side is null when nothing precedes it."""
    try:
        return RedlineOut.model_validate(await redline(db, memo_id=memo_id))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
