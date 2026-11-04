"""Workspace member request and invitation primitive tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.members import MemberAddIn
from app.services.member_tokens import INVITATION_TOKEN_BYTES, hash_invitation_token


def test_member_add_requires_exactly_one_input() -> None:
    assert MemberAddIn(uc_uid="fictional-advisor-002").uc_uid == "fictional-advisor-002"
    assert MemberAddIn.model_validate({"invitation_token": "fictional-token"}).invitation_token
    with pytest.raises(ValidationError):
        MemberAddIn()
    with pytest.raises(ValidationError):
        MemberAddIn.model_validate(
            {"uc_uid": "fictional-advisor-002", "invitation_token": "fictional-token"}
        )


def test_invitation_hash_is_sha256_and_token_entropy_meets_suite_pattern() -> None:
    raw = "fictional-token-for-a-unit-test"
    digest = hash_invitation_token(raw)
    assert len(digest) == 64
    assert digest == hash_invitation_token(raw)
    assert digest != hash_invitation_token(f"{raw}-different")
    assert INVITATION_TOKEN_BYTES >= 32
