from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class Client(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "client"
    __table_args__ = (Index("ix_client_workspace_id", "workspace_id"),)

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    filing_status_default: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    primary_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Link to this taxpayer's Accounting-Ops document vault (the AO workspace +
    # the personal entity), so source tax documents (1099-R, SSA-1099, 1095, …)
    # can be pulled over federation by (entity_id, tax_year). AO owns the OCR;
    # TPO consumes. Both null until linked.
    accounting_ops_workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accounting_ops_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
