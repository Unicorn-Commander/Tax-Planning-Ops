"""workspaces.org_id: the Ops-Center org a workspace belongs to

Revision ID: 0023_workspace_org_binding
Revises: 0022_member_invitations
Create Date: 2026-11-20

The entitlement door asks Ops-Center for tax_ops_access IN the org of the
workspace being entered, so that org must be server-side state, never a
request value. A self-serve workspace is bound to the org Ops-Center answers
for its owner on first entitled use; a named workspace is bound to the org the
creating request was entitled in. Workspaces that predate this column stay
NULL; with ENTITLEMENT_CHECK_ENABLED=true a NULL managed workspace is refused
until it is backfilled by the owner role.

Once bound, the org cannot be changed by any role through UPDATE (trigger):
the runtime role holds UPDATE on workspaces for renames, and a rename must
never be able to move a tenant to another org.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_workspace_org_binding"
down_revision: str | None = "0022_member_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspaces_org_id_immutable() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.org_id IS NOT NULL AND NEW.org_id IS DISTINCT FROM OLD.org_id THEN
                RAISE EXCEPTION 'workspaces.org_id is bound and cannot change';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER workspaces_org_id_immutable
        BEFORE UPDATE OF org_id ON workspaces
        FOR EACH ROW EXECUTE FUNCTION workspaces_org_id_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workspaces_org_id_immutable ON workspaces")
    op.execute("DROP FUNCTION IF EXISTS workspaces_org_id_immutable()")
    op.drop_column("workspaces", "org_id")
