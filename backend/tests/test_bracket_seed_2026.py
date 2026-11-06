"""The 2026 federal seed lives in the phase-1 migration (Rev. Proc. 2025-32).

A database created from that migration already has single/mfj/mfs/hoh/qss for
2026. This locks the figures the position chart looks up, so a later edit
cannot drop the 2026 single set and leave Case and Lab on the empty state.
"""

from __future__ import annotations

from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0002_phase_1_tax_config.py"
)


def test_rev_proc_2025_32_single_ordinary_brackets_are_seeded() -> None:
    text = _MIGRATION.read_text(encoding="utf-8")
    assert "Rev. Proc. 2025-32" in text
    # Standard deduction $16,100. 10% bracket ends at $12,400. Top rate 37%
    # from $640,600. All cents. IRS Rev. Proc. 2025-32, TY2026, single.
    assert '("2026-single", 2026, "single", 1610000)' in text
    assert '(0, 1240000, "0.1000")' in text
    assert '(64060000, None, "0.3700")' in text
