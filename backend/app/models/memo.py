from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class StrategistRun(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """An immutable capture of one AI-strategist run for a tax year: the
    engine-computed findings + the LLM-authored draft memo + the totals, as
    produced by ``generate_strategist_memo``. Persisting the run is what lets a
    memo be edited, signed, and later redlined against the engine output it was
    built from. Nothing in here is ever mutated after creation."""

    __tablename__ = "strategist_run"
    __table_args__ = (
        Index("ix_strategist_run_workspace_id", "workspace_id"),
        Index("ix_strategist_run_tax_year", "client_tax_year_id", "created_at"),
    )

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    # The snapshot the run was computed against (provenance for redline). Nullable
    # because a snapshot can be superseded; we keep the id even if it changes.
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    memo_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_total_tax_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_savings_identified_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    marginal_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    objectives_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    trajectory: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    disclaimer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sha256 over the canonical findings+memo — identity for "did the engine
    # output actually change on re-run" and the basis for a redline.
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_uc_uid: Mapped[str] = mapped_column(String(255), nullable=False)


class Memo(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """A versioned advisor memo for a tax year. Each row is one version. A draft
    starts from a strategist run's ``memo_text``; the advisor edits ``body_md``;
    signing seals it (status='signed', content_hash, an AuditJournal seal event).
    Re-running the strategist + authoring a new version lets the UI redline the
    new body against the last signed one. The human signature is the climax —
    the rarest, most protected action — so it lives on its own immutable row."""

    __tablename__ = "memo"
    __table_args__ = (
        Index("ix_memo_workspace_id", "workspace_id"),
        Index("ix_memo_tax_year_version", "client_tax_year_id", "version", unique=True),
        Index("ix_memo_status", "workspace_id", "status"),
    )

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    strategist_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategist_run.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # 'draft' (editable, sits in the sign-off queue) | 'signed' (sealed, gold).
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    signed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The AuditJournal event id stamped at sign time (the verifiable seal ref).
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # The signed version this draft is intended to supersede (for redline).
    supersedes_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
