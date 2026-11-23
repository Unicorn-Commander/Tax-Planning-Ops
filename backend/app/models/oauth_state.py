from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OAuthState(Base):
    """Single-use PKCE session for the Keycloak login round trip.

    Mints a random `state` (returned to the browser as a cookie and to
    Keycloak as the authorize `state` parameter) plus a PKCE code_verifier,
    and consumes both in the callback BEFORE the token exchange. One row per
    in-flight login; the callback pops the row, so a replayed state finds
    nothing and never reaches the token endpoint.

    Like personal_access_token (0021) this is a global auth table read
    before any workspace GUC is bound, so it carries no RLS.
    """

    __tablename__ = "oauth_state"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    state: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="Random urlsafe token (cookie value + authorize param).",
    )
    code_verifier: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="S256 PKCE verifier; sent at the token exchange.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Hard deadline (mint + 1800 s); refused after this.",
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when the callback consumed the state (replay marker).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
