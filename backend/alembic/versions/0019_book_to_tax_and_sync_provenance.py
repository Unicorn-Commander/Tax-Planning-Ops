"""book-to-tax adjustment + AO sync provenance (the "honest notes")

Two honesty fixes for the Accounting-Ops P&L pull:

1. A synced figure is BOOK net income, not corporate taxable income — they
   differ by Schedule M-1 book-tax adjustments (federal tax per books added
   back, 50% meals, depreciation/§168 vs book, tax-exempt income, …). Add
   ``book_to_tax_adjustment_cents`` (net M-1 adjustment, default 0) so the user
   can reconcile book → taxable; the corporate engine uses
   ``amount_cents + book_to_tax_adjustment_cents`` as pre-NOL taxable income.
   Default 0 → backward-compatible (book used as-is, flagged as an estimate).

2. A synced figure is a snapshot of externally-maintained, possibly-in-progress
   books. Add ``accounting_ops_synced_at`` so the plan can show "as-of" and
   prompt a re-sync.

Both are additive columns on the already-RLS-scoped ``business_entity`` table —
no policy/grant change.

Revision ID: 0019_book_to_tax
Revises: 0018_acctops_entity
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_book_to_tax"
down_revision: str | None = "0018_acctops_entity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "business_entity",
        sa.Column(
            "book_to_tax_adjustment_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "business_entity",
        sa.Column("accounting_ops_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("business_entity", "accounting_ops_synced_at")
    op.drop_column("business_entity", "book_to_tax_adjustment_cents")
