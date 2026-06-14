from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class Engagement(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """The advisory fee on a client engagement — what frames savings as a
    NET-of-fee number on the Present plates ("we saved you $X against a $Y fee").
    One engagement per client per workspace. Fee is integer cents; basis records
    how it's struck so the UI can phrase it honestly (flat / AUM / hourly / value)."""

    __tablename__ = "engagement"
    __table_args__ = (
        Index("ix_engagement_workspace_id", "workspace_id"),
        Index("ix_engagement_client", "client_id", unique=True),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id", ondelete="CASCADE"), nullable=False
    )
    fee_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    # How the fee is struck: flat | aum | hourly | value.
    fee_basis: Mapped[str] = mapped_column(String(16), nullable=False, server_default="flat")
    fee_note: Mapped[str | None] = mapped_column(Text, nullable=True)
