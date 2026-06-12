from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class ClientPlanningProfile(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    """Client-level planning objectives — the goals that make the strategist's
    advice situation-aware.

    One row per client (1:1). These are *intent* fields, not return data: what
    the client is trying to accomplish (retirement timing, a coming liquidity
    event, charitable intent, a planned move) so the strategist can connect the
    engine's findings to the client's actual goals and prioritize accordingly."""

    __tablename__ = "client_planning_profile"
    __table_args__ = (
        Index("ix_client_planning_profile_workspace_id", "workspace_id"),
        Index("ix_client_planning_profile_client", "client_id", unique=True),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id", ondelete="CASCADE"), nullable=False
    )

    # minimize_current_tax | minimize_lifetime_tax | maximize_retirement |
    # wealth_transfer | charitable_legacy | no_preference
    primary_objective: Mapped[str] = mapped_column(
        String(32), nullable=False, default="no_preference"
    )
    retirement_target_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # none | business_sale | equity_compensation | real_estate | inheritance | other
    liquidity_event: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    liquidity_event_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    liquidity_event_amount_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    # none | low | moderate | high | legacy
    charitable_intent: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    annual_giving_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # none | moderate | high
    estate_priority: Mapped[str] = mapped_column(String(16), nullable=False, default="none")

    planned_relocation_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    relocation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # prefer_roth | prefer_traditional | no_preference | advisor_optimize
    roth_preference: Mapped[str] = mapped_column(
        String(20), nullable=False, default="no_preference"
    )
    # conservative | moderate | aggressive
    risk_tolerance: Mapped[str] = mapped_column(String(16), nullable=False, default="moderate")
    # low | medium | high
    cash_flow_sensitivity: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")

    education_funding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # none | sell_external | transfer_family | esop | undecided
    business_succession: Mapped[str] = mapped_column(String(16), nullable=False, default="none")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
