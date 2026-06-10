"""phase 1 tax config

Revision ID: 0002_phase_1
Revises: 0001_phase_0
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase_1"
down_revision: str | None = "0001_phase_0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _federal_aux(year: int, status: str) -> dict:
    niit_thresholds = {
        "single": 20000000,
        "hoh": 20000000,
        "mfj": 25000000,
        "qss": 25000000,
        "mfs": 12500000,
    }
    medicare_thresholds = {
        "single": 20000000,
        "hoh": 20000000,
        "mfj": 25000000,
        "qss": 25000000,
        "mfs": 12500000,
    }
    ltcg = {
        "single": [(0, 4835000, "0.0000"), (4835000, 53340000, "0.1500"), (53340000, None, "0.2000")],
        "hoh": [(0, 6475000, "0.0000"), (6475000, 56670000, "0.1500"), (56670000, None, "0.2000")],
        "mfj": [(0, 9670000, "0.0000"), (9670000, 60005000, "0.1500"), (60005000, None, "0.2000")],
        "qss": [(0, 9670000, "0.0000"), (9670000, 60005000, "0.1500"), (60005000, None, "0.2000")],
        "mfs": [(0, 4835000, "0.0000"), (4835000, 30000000, "0.1500"), (30000000, None, "0.2000")],
    }
    return {
        "tax_year": year,
        "niit": {"threshold_cents": niit_thresholds[status], "rate": "0.0380"},
        "additional_medicare": {
            "threshold_cents": medicare_thresholds[status],
            "rate": "0.0090",
        },
        "capital_loss_limit_cents": 300000,
        "ltcg_brackets": [
            {"lower_bound_cents": lo, "upper_bound_cents": hi, "rate": rate}
            for lo, hi, rate in ltcg[status]
        ],
        "qbi": {"enabled": True},
        "salt": {"cap_cents": 1000000},
        "safe_harbor": {
            "current_year_rate": "0.9000",
            "prior_year_rate": "1.0000",
            "high_agi_prior_year_rate": "1.1000",
            "high_agi_threshold_cents": 15000000,
        },
        "quarterly_due_dates": [
            f"{year}-04-15",
            f"{year}-06-15",
            f"{year}-09-15",
            f"{year + 1}-01-15",
        ],
    }


def upgrade() -> None:
    op.create_table(
        "tax_bracket_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False),
        sa.Column("filing_status", sa.String(length=16), nullable=False),
        sa.Column("standard_deduction_cents", sa.BigInteger(), nullable=False),
        sa.Column("auxiliary_schedules", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "tax_year",
            "jurisdiction",
            "filing_status",
            name="uq_tax_bracket_set_scope",
        ),
    )
    op.create_index(
        "ix_tax_bracket_set_lookup",
        "tax_bracket_set",
        ["workspace_id", "tax_year", "jurisdiction", "filing_status"],
    )
    op.create_table(
        "tax_bracket_row",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bracket_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lower_bound_cents", sa.BigInteger(), nullable=False),
        sa.Column("upper_bound_cents", sa.BigInteger(), nullable=True),
        sa.Column("rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bracket_set_id"], ["tax_bracket_set.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("bracket_set_id", "ordinal", name="uq_tax_bracket_row_ordinal"),
    )
    op.create_index("ix_tax_bracket_row_set", "tax_bracket_row", ["bracket_set_id"])
    op.execute("ALTER TABLE tax_bracket_set OWNER TO tax_planning_ops_owner")
    op.execute("ALTER TABLE tax_bracket_row OWNER TO tax_planning_ops_owner")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tax_bracket_set TO tax_planning_ops_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tax_bracket_row TO tax_planning_ops_app")

    seed_sets = [
        ("2025-single", 2025, "single", 1500000),
        ("2025-mfj", 2025, "mfj", 3000000),
        ("2025-mfs", 2025, "mfs", 1500000),
        ("2025-hoh", 2025, "hoh", 2250000),
        ("2025-qss", 2025, "qss", 3000000),
        ("2026-single", 2026, "single", 1575000),
        ("2026-mfj", 2026, "mfj", 3150000),
        ("2026-mfs", 2026, "mfs", 1575000),
        ("2026-hoh", 2026, "hoh", 2362500),
        ("2026-qss", 2026, "qss", 3150000),
    ]
    brackets = {
        "single": [
            (0, 1192500, "0.1000"),
            (1192500, 4847500, "0.1200"),
            (4847500, 10335000, "0.2200"),
            (10335000, 19730000, "0.2400"),
            (19730000, 25052500, "0.3200"),
            (25052500, 62635000, "0.3500"),
            (62635000, None, "0.3700"),
        ],
        "mfj": [
            (0, 2385000, "0.1000"),
            (2385000, 9695000, "0.1200"),
            (9695000, 20670000, "0.2200"),
            (20670000, 39460000, "0.2400"),
            (39460000, 50105000, "0.3200"),
            (50105000, 75160000, "0.3500"),
            (75160000, None, "0.3700"),
        ],
        "mfs": [
            (0, 1192500, "0.1000"),
            (1192500, 4847500, "0.1200"),
            (4847500, 10335000, "0.2200"),
            (10335000, 19730000, "0.2400"),
            (19730000, 25052500, "0.3200"),
            (25052500, 37580000, "0.3500"),
            (37580000, None, "0.3700"),
        ],
        "hoh": [
            (0, 1700000, "0.1000"),
            (1700000, 6485000, "0.1200"),
            (6485000, 10335000, "0.2200"),
            (10335000, 19730000, "0.2400"),
            (19730000, 25050000, "0.3200"),
            (25050000, 62635000, "0.3500"),
            (62635000, None, "0.3700"),
        ],
        "qss": [
            (0, 2385000, "0.1000"),
            (2385000, 9695000, "0.1200"),
            (9695000, 20670000, "0.2200"),
            (20670000, 39460000, "0.2400"),
            (39460000, 50105000, "0.3200"),
            (50105000, 75160000, "0.3500"),
            (75160000, None, "0.3700"),
        ],
    }
    for set_index, (_seed_id, year, status, standard) in enumerate(seed_sets, start=1):
        set_id = f"00000000-0000-0000-0000-000000010{set_index:03d}"
        op.execute(
            sa.text(
                """
                INSERT INTO tax_bracket_set
                    (id, workspace_id, tax_year, jurisdiction, filing_status,
                     standard_deduction_cents, auxiliary_schedules, notes)
                VALUES
                    (CAST(:id AS uuid), NULL, :year, 'federal', :status, :standard,
                     CAST(:aux AS jsonb), :notes)
                """
            ).bindparams(
                id=set_id,
                year=year,
                status=status,
                standard=standard,
                aux=json.dumps(_federal_aux(year, status)),
                notes=f"Seed federal planning brackets for {year}; verify before production use.",
            )
        )
        for ordinal, (lo, hi, rate) in enumerate(brackets[status], start=1):
            row_id = f"00000000-0000-0000-0000-00000002{set_index:02d}{ordinal:02d}"
            op.execute(
                sa.text(
                    """
                    INSERT INTO tax_bracket_row
                        (id, bracket_set_id, lower_bound_cents, upper_bound_cents, rate, ordinal)
                    VALUES
                        (CAST(:row_id AS uuid), CAST(:set_id AS uuid), :lo, :hi, :rate, :ordinal)
                    """
                ).bindparams(
                    sa.bindparam("row_id", value=row_id),
                    sa.bindparam("set_id", value=set_id),
                    sa.bindparam("lo", value=lo, type_=sa.BigInteger()),
                    sa.bindparam("hi", value=hi, type_=sa.BigInteger()),
                    sa.bindparam("rate", value=Decimal(rate), type_=sa.Numeric(5, 4)),
                    sa.bindparam("ordinal", value=ordinal, type_=sa.Integer()),
                )
            )


def downgrade() -> None:
    op.drop_index("ix_tax_bracket_row_set", table_name="tax_bracket_row")
    op.drop_table("tax_bracket_row")
    op.drop_index("ix_tax_bracket_set_lookup", table_name="tax_bracket_set")
    op.drop_table("tax_bracket_set")
