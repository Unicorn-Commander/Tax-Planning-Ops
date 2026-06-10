from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.lifecycle import bracket_snapshot


def test_bracket_snapshot_is_value_copy() -> None:
    row = SimpleNamespace(
        lower_bound_cents=0,
        upper_bound_cents=None,
        rate=Decimal("0.2400"),
        ordinal=1,
    )
    bracket_set = SimpleNamespace(
        id=uuid4(),
        tax_year=2099,
        jurisdiction="federal",
        filing_status="single",
        standard_deduction_cents=1,
        auxiliary_schedules={"safe_harbor": {"threshold": 1}},
        rows=[row],
    )
    snapshot = bracket_snapshot(bracket_set)  # type: ignore[arg-type]
    row.rate = Decimal("0.9900")
    assert snapshot["rows"][0]["rate"] == "0.2400"
