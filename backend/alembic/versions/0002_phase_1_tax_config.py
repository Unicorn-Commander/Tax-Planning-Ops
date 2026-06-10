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


# LTCG / qualified-dividend 0%/15%/20% breakpoints, in cents, by year+status.
# Verified against IRS Rev. Proc. 2024-40 (TY2025) and Rev. Proc. 2025-32
# (TY2026, first year reflecting OBBBA). MFS = MFJ/2; QSS = MFJ.
_LTCG = {
    2025: {
        "single": [(0, 4835000, "0.0000"), (4835000, 53340000, "0.1500"), (53340000, None, "0.2000")],
        "hoh": [(0, 6475000, "0.0000"), (6475000, 56670000, "0.1500"), (56670000, None, "0.2000")],
        "mfj": [(0, 9670000, "0.0000"), (9670000, 60005000, "0.1500"), (60005000, None, "0.2000")],
        "qss": [(0, 9670000, "0.0000"), (9670000, 60005000, "0.1500"), (60005000, None, "0.2000")],
        "mfs": [(0, 4835000, "0.0000"), (4835000, 30002500, "0.1500"), (30002500, None, "0.2000")],
    },
    2026: {
        "single": [(0, 4945000, "0.0000"), (4945000, 54550000, "0.1500"), (54550000, None, "0.2000")],
        "hoh": [(0, 6620000, "0.0000"), (6620000, 57960000, "0.1500"), (57960000, None, "0.2000")],
        "mfj": [(0, 9890000, "0.0000"), (9890000, 61370000, "0.1500"), (61370000, None, "0.2000")],
        "qss": [(0, 9890000, "0.0000"), (9890000, 61370000, "0.1500"), (61370000, None, "0.2000")],
        "mfs": [(0, 4945000, "0.0000"), (4945000, 30685000, "0.1500"), (30685000, None, "0.2000")],
    },
}

# OBBBA SALT cap (cents): $40,000 in 2025, $40,400 in 2026 (phase-down >500k
# MAGI is assumption-driven in v1, not modeled).
_SALT_CAP = {2025: 4000000, 2026: 4040000}


def _federal_aux(year: int, status: str) -> dict:
    # NIIT + Additional Medicare thresholds are statutory (not inflation
    # indexed): 200k single/hoh, 250k mfj/qss, 125k mfs.
    niit_thresholds = {
        "single": 20000000,
        "hoh": 20000000,
        "mfj": 25000000,
        "qss": 25000000,
        "mfs": 12500000,
    }
    # Safe-harbor high-AGI threshold (prior-year 110% basis): 150k, 75k MFS.
    high_agi = 7500000 if status == "mfs" else 15000000
    return {
        "tax_year": year,
        "niit": {"threshold_cents": niit_thresholds[status], "rate": "0.0380"},
        "additional_medicare": {
            "threshold_cents": niit_thresholds[status],
            "rate": "0.0090",
        },
        "capital_loss_limit_cents": 150000 if status == "mfs" else 300000,
        "ltcg_brackets": [
            {"lower_bound_cents": lo, "upper_bound_cents": hi, "rate": rate}
            for lo, hi, rate in _LTCG[year][status]
        ],
        "qbi": {"enabled": True, "limit_rate": "0.2000"},
        "salt": {"cap_cents": _SALT_CAP[year]},
        "safe_harbor": {
            "current_year_rate": "0.9000",
            "prior_year_rate": "1.0000",
            "high_agi_prior_year_rate": "1.1000",
            "high_agi_threshold_cents": high_agi,
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

    # RLS: the suite-default seed (workspace_id IS NULL) is readable by every
    # tenant; a firm may only read/write its OWN override rows. The app role
    # cannot mutate the NULL seed (WITH CHECK forces its own workspace).
    op.execute("ALTER TABLE tax_bracket_set ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tax_bracket_set FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tax_bracket_set_isolation ON tax_bracket_set
        FOR ALL TO tax_planning_ops_app
        USING (workspace_id IS NULL OR workspace_id = current_workspace_id())
        WITH CHECK (workspace_id = current_workspace_id())
        """
    )
    op.execute("ALTER TABLE tax_bracket_row ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tax_bracket_row FORCE ROW LEVEL SECURITY")
    # Rows inherit their parent set's visibility (no workspace_id of their own).
    op.execute(
        """
        CREATE POLICY tax_bracket_row_isolation ON tax_bracket_row
        FOR ALL TO tax_planning_ops_app
        USING (
            EXISTS (
                SELECT 1 FROM tax_bracket_set s
                WHERE s.id = tax_bracket_row.bracket_set_id
                  AND (s.workspace_id IS NULL OR s.workspace_id = current_workspace_id())
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM tax_bracket_set s
                WHERE s.id = tax_bracket_row.bracket_set_id
                  AND s.workspace_id = current_workspace_id()
            )
        )
        """
    )

    # Standard deductions in cents. 2025 reflects OBBBA (enacted 2025-07-04,
    # retroactive to TY2025): 15,750 / 31,500 / 23,625. 2026 per Rev. Proc.
    # 2025-32: 16,100 / 32,200 / 24,150. MFS = single; QSS = MFJ.
    seed_sets = [
        ("2025-single", 2025, "single", 1575000),
        ("2025-mfj", 2025, "mfj", 3150000),
        ("2025-mfs", 2025, "mfs", 1575000),
        ("2025-hoh", 2025, "hoh", 2362500),
        ("2025-qss", 2025, "qss", 3150000),
        ("2026-single", 2026, "single", 1610000),
        ("2026-mfj", 2026, "mfj", 3220000),
        ("2026-mfs", 2026, "mfs", 1610000),
        ("2026-hoh", 2026, "hoh", 2415000),
        ("2026-qss", 2026, "qss", 3220000),
    ]
    # Ordinary-rate brackets in cents (lower inclusive, upper exclusive).
    # 2025 per IRS Rev. Proc. 2024-40; 2026 per Rev. Proc. 2025-32 (OBBBA).
    # MFS = MFJ/2; QSS = MFJ.
    brackets_by_year = {
        2025: {
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
        },
        2026: {
            "single": [
                (0, 1240000, "0.1000"),
                (1240000, 5040000, "0.1200"),
                (5040000, 10570000, "0.2200"),
                (10570000, 20177500, "0.2400"),
                (20177500, 25622500, "0.3200"),
                (25622500, 64060000, "0.3500"),
                (64060000, None, "0.3700"),
            ],
            "mfj": [
                (0, 2480000, "0.1000"),
                (2480000, 10080000, "0.1200"),
                (10080000, 21140000, "0.2200"),
                (21140000, 40355000, "0.2400"),
                (40355000, 51245000, "0.3200"),
                (51245000, 76870000, "0.3500"),
                (76870000, None, "0.3700"),
            ],
            "mfs": [
                (0, 1240000, "0.1000"),
                (1240000, 5040000, "0.1200"),
                (5040000, 10570000, "0.2200"),
                (10570000, 20177500, "0.2400"),
                (20177500, 25622500, "0.3200"),
                (25622500, 38435000, "0.3500"),
                (38435000, None, "0.3700"),
            ],
            "hoh": [
                (0, 1770000, "0.1000"),
                (1770000, 6745000, "0.1200"),
                (6745000, 10570000, "0.2200"),
                (10570000, 20177500, "0.2400"),
                (20177500, 25620000, "0.3200"),
                (25620000, 64060000, "0.3500"),
                (64060000, None, "0.3700"),
            ],
            "qss": [
                (0, 2480000, "0.1000"),
                (2480000, 10080000, "0.1200"),
                (10080000, 21140000, "0.2200"),
                (21140000, 40355000, "0.2400"),
                (40355000, 51245000, "0.3200"),
                (51245000, 76870000, "0.3500"),
                (76870000, None, "0.3700"),
            ],
        },
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
        for ordinal, (lo, hi, rate) in enumerate(brackets_by_year[year][status], start=1):
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
    op.execute("DROP POLICY IF EXISTS tax_bracket_row_isolation ON tax_bracket_row")
    op.execute("DROP POLICY IF EXISTS tax_bracket_set_isolation ON tax_bracket_set")
    op.drop_index("ix_tax_bracket_row_set", table_name="tax_bracket_row")
    op.drop_table("tax_bracket_row")
    op.drop_index("ix_tax_bracket_set_lookup", table_name="tax_bracket_set")
    op.drop_table("tax_bracket_set")
