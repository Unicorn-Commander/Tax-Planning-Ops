"""phase 2 extraction baseline

Revision ID: 0003_phase_2
Revises: 0002_phase_1
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase_2"
down_revision: str | None = "0002_phase_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = [
    "client_tax_year",
    "document",
    "extracted_return",
    "tax_situation_snapshot",
    "audit_journal",
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "client_tax_year",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("filing_status", sa.String(length=16), nullable=False),
        sa.Column("source_year_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_client_tax_year_workspace_id", "client_tax_year", ["workspace_id"])
    op.create_index(
        "ix_client_tax_year_client_year", "client_tax_year", ["client_id", "tax_year"], unique=True
    )

    op.create_table(
        "document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_blob_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_workspace_id", "document", ["workspace_id"])

    op.create_table(
        "extracted_return",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_blob_key", sa.Text(), nullable=False),
        sa.Column("form_type", sa.String(length=24), nullable=False),
        sa.Column("ocr_job_id", sa.String(length=255), nullable=True),
        sa.Column("extraction_status", sa.String(length=32), nullable=False),
        sa.Column("overall_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("extraction_raw", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_extracted_return_workspace_id", "extracted_return", ["workspace_id"])
    op.create_index(
        "ix_extracted_return_tax_year", "extracted_return", ["client_tax_year_id"], unique=True
    )

    op.create_table(
        "extracted_field",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("extracted_return_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("value_cents", sa.BigInteger(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=True),
        sa.Column("corrected_value_cents", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["extracted_return_id"], ["extracted_return.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_extracted_field_return", "extracted_field", ["extracted_return_id"])
    op.create_index("ix_extracted_field_key", "extracted_field", ["field_key"])

    op.create_table(
        "tax_situation_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("bracket_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_income_cents", sa.BigInteger(), nullable=False),
        sa.Column("agi_cents", sa.BigInteger(), nullable=False),
        sa.Column("taxable_income_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("marginal_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("effective_rate", sa.Numeric(8, 6), nullable=False),
        sa.Column("has_manual_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_tax_situation_snapshot_workspace_id", "tax_situation_snapshot", ["workspace_id"]
    )

    op.create_table(
        "audit_journal",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_uc_uid", sa.String(length=255), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False, unique=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_journal_workspace_id", "audit_journal", ["workspace_id"])

    for table in [*WORKSPACE_TABLES, "extracted_field"]:
        op.execute(f"ALTER TABLE {table} OWNER TO tax_planning_ops_owner")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO tax_planning_ops_app")

    for table in WORKSPACE_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            FOR ALL TO tax_planning_ops_app
            USING (workspace_id = current_workspace_id())
            WITH CHECK (workspace_id = current_workspace_id())
            """
        )

    op.execute("ALTER TABLE extracted_field ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extracted_field FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY extracted_field_workspace_isolation ON extracted_field
        FOR ALL TO tax_planning_ops_app
        USING (
            EXISTS (
                SELECT 1 FROM extracted_return er
                WHERE er.id = extracted_field.extracted_return_id
                  AND er.workspace_id = current_workspace_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM extracted_return er
                WHERE er.id = extracted_field.extracted_return_id
                  AND er.workspace_id = current_workspace_id()
            )
        )
        """
    )


def downgrade() -> None:
    op.drop_table("audit_journal")
    op.drop_table("tax_situation_snapshot")
    op.drop_table("extracted_field")
    op.drop_table("extracted_return")
    op.drop_table("document")
    op.drop_index("ix_client_tax_year_client_year", table_name="client_tax_year")
    op.drop_index("ix_client_tax_year_workspace_id", table_name="client_tax_year")
    op.drop_table("client_tax_year")
