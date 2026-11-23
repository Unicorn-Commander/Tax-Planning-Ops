"""oauth_state — single-use PKCE state for the Keycloak login round trip.

The SSO callback used to trust whatever `code` the browser carried: an
attacker could start their own login, hand the victim the final authorize URL,
and finish the victim's session with the ATTACKER's code (login CSRF; the
victim signs in as the attacker and uploads land in the attacker's account).

This table stores, per in-flight login, the random `state` (sent to the
browser as a __Host- cookie and to Keycloak as the authorize parameter) plus
the PKCE code_verifier, with a 1800 s TTL. The callback compares the query
state against the cookie, pops the row BEFORE the token exchange (so a replay
finds nothing), and sends the verifier in the exchange.

Like personal_access_token (0021) this is a global auth table read before any
workspace GUC is bound: no RLS, no per-tenant data, owner/grants mirror 0017.

Revision ID: 0026_oauth_state_pkce
Revises: 0025_ao_link_verification
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026_oauth_state_pkce"
down_revision: str | None = "0025_ao_link_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "tax_planning_ops_app"
OWNER_ROLE = "tax_planning_ops_owner"


def upgrade() -> None:
    op.create_table(
        "oauth_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "state",
            sa.String(length=128),
            nullable=False,
            comment="Random urlsafe token, 32+ bytes of entropy. Cookie value and "
            "the authorize `state` parameter; matched before any token exchange.",
        ),
        sa.Column(
            "code_verifier",
            sa.String(length=128),
            nullable=False,
            comment="S256 PKCE verifier. Sent as code_verifier at the token "
            "exchange; the S256 challenge went out on the authorize request.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Hard deadline (mint + 1800 s). A row past this is refused, "
            "never exchanged.",
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set when the callback consumed the state. A non-null value "
            "marks a replayed state.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The callback looks up by state (the query param matched against the cookie).
    op.create_index("ix_oauth_state_state", "oauth_state", ["state"], unique=True)

    op.execute(f"ALTER TABLE oauth_state OWNER TO {OWNER_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_state TO {RUNTIME_ROLE}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON oauth_state FROM {RUNTIME_ROLE}")
    op.drop_index("ix_oauth_state_state", table_name="oauth_state")
    op.drop_table("oauth_state")
