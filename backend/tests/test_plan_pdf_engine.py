from __future__ import annotations

from app.engines.plan_pdf import DISCLAIMER, BrandingPayload, assemble_plan_pdf_payload


def test_plan_pdf_payload_includes_disclaimer_and_override_footnote() -> None:
    payload = assemble_plan_pdf_payload(
        branding=BrandingPayload(firm_name="Firm"),
        client_name="Client",
        tax_year=2099,
        current={"total_tax_cents": 1},
        next_year={"total_tax_cents": 2},
        strategies=[{"name": "Strategy", "estimated_savings_cents": 10}],
        quarterly=[{"quarter": 1, "required_payment_cents": 20}],
        has_manual_override=True,
        bracket_provenance="bracket-set-id",
    )
    assert payload.disclaimer == DISCLAIMER
    assert any("Manual overrides" in footnote for footnote in payload.footnotes)
    assert payload.branding.firm_name == "Firm"
