"""Cryptographic primitives for workspace invitations."""

from __future__ import annotations

import hashlib
import secrets

INVITATION_TOKEN_BYTES = 32


def hash_invitation_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest stored for an invitation token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_invitation_token() -> str:
    """Create a 256-bit URL-safe token; only the create response sees it."""
    return secrets.token_urlsafe(INVITATION_TOKEN_BYTES)
