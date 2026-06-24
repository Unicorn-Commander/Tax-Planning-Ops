"""accounting-ops tax-document federation: client link + per-year source-doc manifest

The OCR consumer side of the Accounting-Ops federation. AO owns the document
vault + OCR; TPO reads the structured extractions (1099-R, SSA-1099, 1095, …)
over the shared-Keycloak M2M rail and stores them per tax year. All additive,
all nullable — no policy or grant change (both ``client`` and ``client_tax_year``
are already RLS-scoped by ``workspace_id``, and the app role already holds DML on
them, so the new columns are covered):

  client.accounting_ops_workspace_id       — AO workspace holding this taxpayer's docs
  client.accounting_ops_entity_id          — AO (personal) entity to pull by
  client_tax_year.source_documents          — JSONB manifest of pulled extractions (per year)
  client_tax_year.source_documents_synced_at — "as-of" for an honest staleness note

Revision ID: 0020_acctops_tax_docs
Revises: 0019_book_to_tax
Create Date: 2026-06-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_acctops_tax_docs"
down_revision: str | None = "0019_book_to_tax"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "client",
        sa.Column("accounting_ops_workspace_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "client",
        sa.Column("accounting_ops_entity_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "client_tax_year",
        sa.Column(
            "source_documents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "client_tax_year",
        sa.Column(
            "source_documents_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("client_tax_year", "source_documents_synced_at")
    op.drop_column("client_tax_year", "source_documents")
    op.drop_column("client", "accounting_ops_entity_id")
    op.drop_column("client", "accounting_ops_workspace_id")
