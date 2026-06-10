from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class StrategyLibrary(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "strategy_library"
    __table_args__ = (Index("ix_strategy_library_workspace_id", "workspace_id"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    client_facing_copy: Mapped[str] = mapped_column(Text, nullable=False)
    default_amount_cents: Mapped[int | None] = mapped_column(nullable=True)
    savings_method: Mapped[str] = mapped_column(String(32), nullable=False)
    custom_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    applicability_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    statutory_cap_cents: Mapped[int | None] = mapped_column(nullable=True)
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_year_applicability: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


class ClientStrategy(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "client_strategy"
    __table_args__ = (Index("ix_client_strategy_workspace_id", "workspace_id"),)

    client_tax_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_tax_year.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_library.id"), nullable=False
    )
    disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_cents: Mapped[int] = mapped_column(nullable=False)
    effective_rate_used: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    estimated_savings_cents: Mapped[int] = mapped_column(nullable=False)
    status_flag: Mapped[str] = mapped_column(String(32), nullable=False)
    advisor_note: Mapped[str | None] = mapped_column(Text, nullable=True)
