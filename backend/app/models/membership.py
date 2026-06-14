from __future__ import annotations

import uuid

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin


class WorkspaceMembership(IdMixin, TimestampMixin, Base):
    """Which named workspaces a user (Keycloak ``sub`` / uc_uid) owns or has
    joined. This is what makes the suite SSO genuinely multi-workspace: the token
    hands out one home workspace, and a user can create more (e.g. a personal
    file + a company file) and switch between them. RLS scopes the table to the
    caller's uc_uid (``current_uc_uid()``), so a user only ever sees their own
    memberships — selection of a workspace is authorized against this table."""

    __tablename__ = "workspace_membership"
    __table_args__ = (
        UniqueConstraint("user_uc_uid", "workspace_id", name="uq_membership_user_workspace"),
        Index("ix_workspace_membership_user", "user_uc_uid"),
        Index("ix_workspace_membership_workspace", "workspace_id"),
    )

    user_uc_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Denormalised workspace name — lets the switcher list a user's workspaces
    # without reading the RLS-protected workspaces table (scoped to the active
    # one). Kept in sync on rename.
    workspace_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="owner")
