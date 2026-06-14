"""Implementation tasks — the 5-field contracts (spec §9.4).

WHO (owner) does WHAT (title), moving how much CASH (amount_cents), by WHEN
(due_date, optionally resolved from a statutory_key), tracked to a STATUS. A task
may implement an accepted ``ClientStrategy`` or stand free (e.g. "send Q4
voucher"). This module is plain CRUD over ``ImplementationTask``; the only logic
is convenience seeding (resolve a statutory date / inherit a strategy's amount)
and stamping evidence on completion. No dollar figure is computed here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.implementation import ImplementationTask
from app.models.strategy import ClientStrategy
from app.models.tax_year import ClientTaxYear
from app.schemas.tasks import TaskCreateIn, TaskUpdateIn
from app.statutory_deadlines import resolve_deadline


async def list_tasks(
    db: AsyncSession, *, client_tax_year_id: UUID
) -> list[ImplementationTask]:
    """Live (non-soft-deleted) contract rows for a plan year, in board order.

    RLS already scopes to the workspace; we filter to the plan year and drop
    soft-deleted rows."""
    rows = await db.scalars(
        select(ImplementationTask)
        .where(
            ImplementationTask.client_tax_year_id == client_tax_year_id,
            ImplementationTask.deleted_at.is_(None),
        )
        .order_by(ImplementationTask.sort_order, ImplementationTask.created_at)
    )
    return list(rows.all())


async def create_task(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    client_tax_year_id: UUID,
    payload: TaskCreateIn,
) -> ImplementationTask:
    """Create a contract row under ``client_tax_year_id``.

    Convenience seeding:
      * a ``statutory_key`` with no explicit ``due_date`` resolves the date from
        the static catalog (using the plan year's ``tax_year``);
      * a ``client_strategy_id`` with no explicit ``amount_cents`` inherits the
        strategy's ``amount_cents`` (the dollars it moves).

    Raises ``LookupError`` if the plan year doesn't exist (or isn't visible to
    this workspace under RLS)."""
    tax_year = await db.get(ClientTaxYear, client_tax_year_id)
    if tax_year is None:
        raise LookupError("tax year not found")

    due_date = payload.due_date
    if due_date is None and payload.statutory_key is not None:
        resolved = resolve_deadline(payload.statutory_key, tax_year.tax_year)
        if resolved is not None:
            # Store as a tz-aware datetime at midnight UTC (column is timestamptz).
            due_date = datetime(resolved.year, resolved.month, resolved.day, tzinfo=UTC)

    amount_cents = payload.amount_cents
    if amount_cents is None and payload.client_strategy_id is not None:
        strategy = await db.get(ClientStrategy, payload.client_strategy_id)
        if strategy is not None:
            amount_cents = strategy.amount_cents

    task = ImplementationTask(
        workspace_id=workspace_id,
        client_tax_year_id=client_tax_year_id,
        client_strategy_id=payload.client_strategy_id,
        title=payload.title,
        owner=payload.owner,
        amount_cents=amount_cents,
        due_date=due_date,
        statutory_key=payload.statutory_key,
        sort_order=payload.sort_order,
        note=payload.note,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


# Only these fields are advisor-editable via PATCH; ``status`` and evidence are
# handled with the extra completion logic below.
_SIMPLE_UPDATE_FIELDS = (
    "title",
    "owner",
    "amount_cents",
    "due_date",
    "statutory_key",
    "sort_order",
    "evidence_blob_key",
    "note",
)


async def update_task(
    db: AsyncSession, *, task_id: UUID, payload: TaskUpdateIn
) -> ImplementationTask:
    """Apply a partial update. Only fields the caller actually set are touched
    (so an omitted field is left alone, but an explicit ``null`` clears it).

    When the status moves to 'done' and an ``evidence_blob_key`` is present
    (carried in this same patch or already on the row), stamp
    ``evidence_uploaded_at``. Raises ``LookupError`` if the task is missing."""
    task = await db.get(ImplementationTask, task_id)
    if task is None or task.deleted_at is not None:
        raise LookupError("task not found")

    fields_set = payload.model_dump(exclude_unset=True)
    for field in _SIMPLE_UPDATE_FIELDS:
        if field in fields_set:
            setattr(task, field, fields_set[field])
    if "status" in fields_set:
        task.status = fields_set["status"]
    # Record when proof-of-completion landed (idempotent: only the first time).
    if task.status == "done" and task.evidence_blob_key and task.evidence_uploaded_at is None:
        task.evidence_uploaded_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(task)
    return task


async def delete_task(db: AsyncSession, *, task_id: UUID) -> None:
    """Soft-delete a contract row (set ``deleted_at``). Raises ``LookupError``
    if it's missing or already deleted."""
    task = await db.get(ImplementationTask, task_id)
    if task is None or task.deleted_at is not None:
        raise LookupError("task not found")
    task.deleted_at = datetime.now(UTC)
    await db.flush()
