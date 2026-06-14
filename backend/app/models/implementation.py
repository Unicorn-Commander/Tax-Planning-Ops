from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class ImplementationTask(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """A 5-field implementation contract on an accepted strategy: WHO does WHAT,
    moving how much CASH, by WHEN (a statutory or advisor deadline), tracked to a
    STATUS with optional evidence. This is what turns a signed plan into a chase
    list — it powers the Plan surface's contract rows and the season board."""

    __tablename__ = "implementation_task"
    __table_args__ = (
        Index("ix_implementation_task_workspace_id", "workspace_id"),
        Index("ix_implementation_task_tax_year", "client_tax_year_id"),
        Index("ix_implementation_task_strategy", "client_strategy_id"),
    )

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    # The accepted strategy this task implements (nullable: a task can be free-
    # standing, e.g. "send Q4 voucher"). SET NULL so retiring a strategy keeps
    # the task's history.
    client_strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_strategy.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Field 1 — WHAT: the action.
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Field 2 — WHO: the responsible party (Client / Advisor / Custodian / CPA…).
    owner: Mapped[str] = mapped_column(String(64), nullable=False, server_default="advisor")
    # Field 3 — CASH: the dollars moving (nullable for non-monetary actions).
    amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Field 4 — WHEN: the deadline. ``statutory_key`` links to the static
    # statutory-deadline catalog (e.g. "q4_estimate", "form_8606", "secure_act_rmd")
    # so the UI can show the citation; ``due_date`` is the resolved date.
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    statutory_key: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # Field 5 — STATUS: open | in_progress | done | blocked | dismissed.
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="open")
    # Optional evidence of completion (Garage blob key + when it landed).
    evidence_blob_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RealizedOutcome(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """The renewal number: what a planned strategy actually delivered, measured
    against next year's return or the client's books. ``planned_savings_cents``
    is locked from the strategy estimate at reconciliation time; ``realized_*``
    is the measured actual. The per-strategy and rolled-up realized figures are
    the only ones in the product (besides signed memos) that wear gold."""

    __tablename__ = "realized_outcome"
    __table_args__ = (
        Index("ix_realized_outcome_workspace_id", "workspace_id"),
        Index("ix_realized_outcome_tax_year", "client_tax_year_id"),
        Index("ix_realized_outcome_strategy", "client_strategy_id"),
    )

    # The PLAN year being reconciled.
    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    client_strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_strategy.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The year the outcome was observed in (the plan-year + 1, typically).
    realized_tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_savings_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    realized_savings_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    realized_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # How the actual was sourced: next_year_return | books | manual.
    basis: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")
    # A pointer into the source (extracted_return id, AO pull ref, etc.).
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reconciled_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
