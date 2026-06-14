from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.tasks import StatutoryDeadlineOut, TaskCreateIn, TaskOut, TaskUpdateIn
from app.services.tasks import create_task, delete_task, list_tasks, update_task
from app.statutory_deadlines import list_statutory_deadlines

router = APIRouter(tags=["tasks"])


@router.get("/plans/{client_tax_year_id}/tasks", response_model=list[TaskOut])
async def get_tasks(
    client_tax_year_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[TaskOut]:
    """The implementation contract rows for a plan year, in board order. RLS
    scopes to the workspace; soft-deleted rows are excluded."""
    tasks = await list_tasks(db, client_tax_year_id=client_tax_year_id)
    return [TaskOut.model_validate(task) for task in tasks]


@router.post("/plans/{client_tax_year_id}/tasks", response_model=TaskOut, status_code=201)
async def post_task(
    client_tax_year_id: UUID,
    payload: TaskCreateIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> TaskOut:
    """Add a contract row. A ``statutory_key`` without a ``due_date`` resolves
    the deadline from the catalog; a ``client_strategy_id`` without an
    ``amount_cents`` inherits the strategy's amount."""
    try:
        task = await create_task(
            db,
            workspace_id=ctx.workspace_id,
            client_tax_year_id=client_tax_year_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return TaskOut.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    task_id: UUID,
    payload: TaskUpdateIn,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> TaskOut:
    """Update a contract row (partial). Moving status to 'done' with evidence
    attached stamps the evidence timestamp."""
    try:
        task = await update_task(db, task_id=task_id, payload=payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return TaskOut.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task_endpoint(
    task_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Soft-delete a contract row."""
    try:
        await delete_task(db, task_id=task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/statutory-deadlines", response_model=list[StatutoryDeadlineOut])
async def get_statutory_deadlines(
    tax_year: int = Query(..., ge=1900, le=2100),
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> list[StatutoryDeadlineOut]:
    """The static statutory-deadline catalog resolved to calendar dates for the
    given tax year, in chase order. Reference data — no DB, no workspace state."""
    return [
        StatutoryDeadlineOut.model_validate(entry)
        for entry in list_statutory_deadlines(tax_year)
    ]
