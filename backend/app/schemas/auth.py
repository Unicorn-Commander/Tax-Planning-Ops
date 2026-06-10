from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceMembership(BaseModel):
    workspace_id: UUID = Field(alias="workspaceId")
    slug: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    role: str = "advisor"
    is_default: bool = Field(default=False, alias="isDefault")


class AuthContext(BaseModel):
    claims: dict[str, Any]
    uc_uid: str
    workspace_id: UUID
    authorized_workspace_ids: set[UUID]
    scopes: set[str]


class MeResponse(BaseModel):
    sub: str
    workspace_id: UUID
    authorized_workspace_ids: list[UUID]
    scopes: list[str]
    claims: dict[str, Any]
