from __future__ import annotations

from app.engines.form1040 import Form1040Inputs, calculate_form1040
from app.engines.projection import project_tax_situation
from tests.test_form1040_engine import _config


def test_projection_matches_form1040_for_identical_inputs() -> None:
    inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    config = _config()
    base = calculate_form1040(inputs, config)
    projected = project_tax_situation(inputs, config).projected
    assert projected.total_tax_cents == base.total_tax_cents
    assert projected.marginal_rate == base.marginal_rate
    assert projected.effective_rate == base.effective_rate


def test_projection_delta_vs_base() -> None:
    config = _config()
    base = calculate_form1040(Form1040Inputs(filing_status="single", wages_cents=5_000_000), config)
    projection = project_tax_situation(
        Form1040Inputs(filing_status="single", wages_cents=10_000_000),
        config,
        base,
    )
    assert projection.delta is not None
    assert projection.delta.total_tax_cents == 1_350_000
