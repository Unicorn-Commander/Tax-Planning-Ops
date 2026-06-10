from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class TaxBracketSet(IdMixin, TimestampMixin, Base):
    __tablename__ = "tax_bracket_set"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "tax_year",
            "jurisdiction",
            "filing_status",
            name="uq_tax_bracket_set_scope",
        ),
        Index(
            "ix_tax_bracket_set_lookup",
            "workspace_id",
            "tax_year",
            "jurisdiction",
            "filing_status",
        ),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(32), nullable=False, default="federal")
    filing_status: Mapped[str] = mapped_column(String(16), nullable=False)
    standard_deduction_cents: Mapped[int] = mapped_column(nullable=False)
    auxiliary_schedules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rows: Mapped[list[TaxBracketRow]] = relationship(
        back_populates="bracket_set",
        cascade="all, delete-orphan",
        order_by="TaxBracketRow.ordinal",
    )


class TaxBracketRow(IdMixin, Base):
    __tablename__ = "tax_bracket_row"
    __table_args__ = (
        UniqueConstraint("bracket_set_id", "ordinal", name="uq_tax_bracket_row_ordinal"),
        Index("ix_tax_bracket_row_set", "bracket_set_id"),
    )

    bracket_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_bracket_set.id", ondelete="CASCADE"), nullable=False
    )
    lower_bound_cents: Mapped[int] = mapped_column(nullable=False)
    upper_bound_cents: Mapped[int | None] = mapped_column(nullable=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    bracket_set: Mapped[TaxBracketSet] = relationship(back_populates="rows")
