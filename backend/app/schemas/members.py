"""Request shapes for workspace member management."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class MemberAddIn(BaseModel):
    uc_uid: str | None = Field(default=None, min_length=1, max_length=255)
    invitation_token: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("uc_uid", "invitation_token")
    @classmethod
    def _strip_value(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> MemberAddIn:
        if bool(self.uc_uid) == bool(self.invitation_token):
            raise ValueError("provide exactly one of uc_uid or invitation_token")
        return self
