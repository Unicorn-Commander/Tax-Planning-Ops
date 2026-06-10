from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IdMixin, TimestampMixin, WorkspaceScopedMixin


class WorkspaceBranding(IdMixin, WorkspaceScopedMixin, TimestampMixin, Base):
    __tablename__ = "workspace_branding"

    firm_name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_blob_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str] = mapped_column(String(32), nullable=False, default="#0f766e")
    advisor_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
