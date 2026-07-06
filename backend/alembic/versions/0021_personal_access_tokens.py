"""personal_access_token — user-minted long-lived MCP tokens (tpo_pat_*)

Adds the durable-token auth path so TPO can be a persistent Claude Code MCP
server: a user mints a ``tpo_pat_<...>`` bearer that external AI clients present
when calling the ``/api/v1/mcp`` surface (and any REST endpoint). Every request
bearing that token validates fast (sha256 hash lookup on the indexed prefix) and
resolves to the owner's AuthContext WITHOUT a Keycloak round-trip.

Storage shape (one row per token):
  * ``secret_hash``   = raw sha256(token).digest()   -- 32 bytes BYTEA
  * ``secret_prefix`` = first 12 chars of the token  -- e.g. 'tpo_pat_a3f9'

The prefix is INDEXED so a request's bearer resolves in O(1): look up by prefix
-> constant-time compare the full sha256 hash. The prefix alone is non-secret.

TPO-specific vs Accounting-Ops's 0010 migration:
  * TPO is claim-based (no ``user_account`` table), so the token is keyed by
    ``owner_uc_uid TEXT`` (the Keycloak ``uc_uid``/``sub``) — no FK, no JOIN.
  * This is a GLOBAL/public auth table, looked up in the auth middleware BEFORE
    any workspace GUC is bound. It therefore has NO row-level security (unlike
    ``workspace_membership``); owner scoping is enforced in the query WHERE
    clause. RLS here would break the pre-workspace lookup and is unnecessary
    because the table holds no per-workspace tenant data.

Runtime grants: the NOBYPASSRLS runtime role ``tax_planning_ops_app`` needs
SELECT (lookup), INSERT (mint), UPDATE (last_used_at + revoke flip), DELETE
(owner hard-delete). Table is owned by ``tax_planning_ops_owner`` (mirrors the
0017 workspace_membership pattern) so the app role is a non-owner grantee.

Revision ID: 0021_personal_access_tokens
Revises: 0020_acctops_tax_docs
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_personal_access_tokens"
down_revision: str | None = "0020_acctops_tax_docs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "tax_planning_ops_app"
OWNER_ROLE = "tax_planning_ops_owner"


def upgrade() -> None:
    op.create_table(
        "personal_access_token",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_uc_uid",
            sa.Text(),
            nullable=False,
            comment="Keycloak uc_uid/sub of the minting user. Token acts as them.",
        ),
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            comment="User-supplied label, e.g. 'Claude Code — laptop'.",
        ),
        sa.Column(
            "secret_hash",
            postgresql.BYTEA(),
            nullable=False,
            comment="Raw sha256(token) bytes. 32 bytes. Compared constant-time.",
        ),
        sa.Column(
            "secret_prefix",
            sa.Text(),
            nullable=False,
            comment="First 12 chars of the token (e.g. 'tpo_pat_a3f9'). "
            "Indexed for fast lookup; non-secret — safe to display + log.",
        ),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
            comment="Subset of the owner's scopes "
            "(taxplan:advisor, taxplan:admin).",
        ),
        sa.Column(
            "workspace_scope",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
            comment="Optional workspace UUIDs the PAT may access. "
            "NULL = self-serve (owner's uuid5(sub) workspace).",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="NULL = never expires. Default 90 days (enforced at the API "
            "layer, not server_default).",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Updated on each successful auth (fire-and-forget).",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete. Revoked tokens fail auth immediately.",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Hot path: every request with a `tpo_pat_*` bearer looks up by prefix.
    op.create_index(
        "ix_personal_access_token_secret_prefix",
        "personal_access_token",
        ["secret_prefix"],
    )
    # Listing a user's own tokens.
    op.create_index(
        "ix_personal_access_token_owner_uc_uid",
        "personal_access_token",
        ["owner_uc_uid"],
    )

    # Ownership + runtime grants (mirrors the 0017 workspace_membership pattern).
    # NO RLS on this global auth table: it is read in the middleware before any
    # workspace GUC is set, and owner scoping lives in the query WHERE clause.
    op.execute(f"ALTER TABLE personal_access_token OWNER TO {OWNER_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON personal_access_token "
        f"TO {RUNTIME_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE ALL ON personal_access_token FROM {RUNTIME_ROLE}"
    )
    op.drop_index(
        "ix_personal_access_token_owner_uc_uid",
        table_name="personal_access_token",
    )
    op.drop_index(
        "ix_personal_access_token_secret_prefix",
        table_name="personal_access_token",
    )
    op.drop_table("personal_access_token")
