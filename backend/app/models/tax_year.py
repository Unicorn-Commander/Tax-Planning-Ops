from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class ClientTaxYear(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "client_tax_year"
    __table_args__ = (
        Index("ix_client_tax_year_workspace_id", "workspace_id"),
        Index("ix_client_tax_year_client_year", "client_id", "tax_year", unique=True),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id", ondelete="CASCADE"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_year_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Document(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "document"
    __table_args__ = (Index("ix_document_workspace_id", "workspace_id"),)

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_blob_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class ExtractedReturn(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "extracted_return"
    __table_args__ = (
        Index("ix_extracted_return_workspace_id", "workspace_id"),
        Index("ix_extracted_return_tax_year", "client_tax_year_id", unique=True),
    )

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    source_blob_key: Mapped[str] = mapped_column(Text, nullable=False)
    form_type: Mapped[str] = mapped_column(String(24), nullable=False)
    ocr_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    extraction_raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    fields: Mapped[list[ExtractedField]] = relationship(
        back_populates="extracted_return",
        cascade="all, delete-orphan",
        order_by="ExtractedField.field_key",
    )


class ExtractedField(IdMixin, Base):
    __tablename__ = "extracted_field"
    __table_args__ = (
        Index("ix_extracted_field_return", "extracted_return_id"),
        Index("ix_extracted_field_key", "field_key"),
    )

    extracted_return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_return.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_cents: Mapped[int | None] = mapped_column(nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    corrected_value_cents: Mapped[int | None] = mapped_column(nullable=True)

    extracted_return: Mapped[ExtractedReturn] = relationship(back_populates="fields")


class TaxSituationSnapshot(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "tax_situation_snapshot"
    __table_args__ = (Index("ix_tax_situation_snapshot_workspace_id", "workspace_id"),)

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    bracket_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    total_income_cents: Mapped[int] = mapped_column(nullable=False)
    agi_cents: Mapped[int] = mapped_column(nullable=False)
    taxable_income_cents: Mapped[int] = mapped_column(nullable=False)
    total_tax_cents: Mapped[int] = mapped_column(nullable=False)
    marginal_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    effective_rate: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    has_manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AuditJournal(IdMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "audit_journal"
    __table_args__ = (Index("ix_audit_journal_workspace_id", "workspace_id"),)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_uc_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
