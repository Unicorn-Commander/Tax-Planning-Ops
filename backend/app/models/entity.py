from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class BusinessEntity(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """A pass-through business interest attached to a client tax year.

    One row per Schedule C / partnership K-1 / S-corp K-1 / Schedule E rental.
    `kind` discriminates which fields are meaningful; the aggregation service
    maps each row to the matching passthrough-engine entity. `amount_cents` is
    the primary figure (net profit / K-1 box-1 ordinary income / net rental,
    any of which may be negative)."""

    __tablename__ = "business_entity"
    __table_args__ = (
        Index("ix_business_entity_workspace_id", "workspace_id"),
        Index("ix_business_entity_tax_year", "client_tax_year_id"),
    )

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    # schedule_c | partnership_k1 | s_corp_k1 | schedule_e
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    w2_wages_paid_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ubia_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    guaranteed_payments_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shareholder_w2_wages_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    is_general_partner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_sstb: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_qbi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # C-corp only: dividends distributed to the owner (→ qualified dividends on
    # the 1040) and the corporation's available NOL carryforward.
    dividends_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    nol_available_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Optional link to an Accounting-Ops workspace whose P&L net income feeds
    # this entity's `amount_cents` on a "Pull from Accounting-Ops" sync.
    accounting_ops_workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Optional: scope the P&L pull to ONE entity within that AO workspace (a
    # workspace can hold several books). Unset → workspace-level consolidated.
    accounting_ops_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # When the AO figure was last pulled (a synced figure is a snapshot of
    # externally-maintained, possibly-in-progress books → show "as-of" + re-sync).
    accounting_ops_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Net Schedule M-1 book-to-tax adjustment. A synced amount_cents is BOOK net
    # income; corporate taxable income = amount_cents + this. Default 0 (book
    # used as-is, flagged as an estimate).
    book_to_tax_adjustment_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
