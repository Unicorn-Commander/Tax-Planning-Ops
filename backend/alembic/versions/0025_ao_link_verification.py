"""AO link verification provenance on client + business_entity.

A link to an Accounting-Ops workspace used to be stored unvalidated, and the
P&L / tax-document pulls ran with TPO's own service token — which AO floors to
viewer on ANY workspace — so a link pointed at another tenant's AO workspace
leaked that tenant's P&L and tax documents through TPO (confused deputy).

Links are now verified at set-time against AO with the linker's own bearer, and
this migration records the provenance that makes "verified" queryable:

  client.accounting_ops_linked_at / _linked_by
  business_entity.accounting_ops_linked_at / _linked_by

Null on every existing row = UNVERIFIED: the sync services refuse to call AO
for such a link until it is re-set through the verified path. All additive,
all nullable; both tables are already RLS-scoped and the app role already
holds DML, so no policy or grant change.

Revision ID: 0025_ao_link_verification
Revises: 0024_membership_lock
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_ao_link_verification"
down_revision: str | None = "0024_membership_lock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("client", "business_entity"):
        op.add_column(
            table,
            sa.Column("accounting_ops_linked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("accounting_ops_linked_by", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    for table in ("client", "business_entity"):
        op.drop_column(table, "accounting_ops_linked_by")
        op.drop_column(table, "accounting_ops_linked_at")
