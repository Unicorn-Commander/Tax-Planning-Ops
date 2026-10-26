"""Demo dataset is well-formed (no live DB needed).

These assert the catalog in ``app.services.demo_seed`` is internally consistent
and speaks the schemas/field-keys the seeding services expect, so a broken demo
fails here rather than at load time. A real end-to-end seed against Postgres is
covered the same way as tests/test_rls_integration.py (skipped without a DB).
"""

from __future__ import annotations

from app.schemas.client import ClientCreate
from app.schemas.extraction import ClientTaxYearCreate, CorrectFieldRequest
from app.schemas.quarterly import ComputeQuarterlyRequest
from app.schemas.strategy import AddClientStrategyRequest, StrategyLibraryIn
from app.services.demo_seed import (
    CLIENTS,
    DEMO_BASE_TAX_YEAR,
    DEMO_PLAN_TAX_YEAR,
    STRATEGIES,
    STRATEGY_CATEGORIES,
)
from app.services.extraction import CANONICAL_1040_FIELD_KEYS

_VALID_FILING_STATUSES = {"single", "mfj", "mfs", "hoh", "qss"}


def test_strategy_catalog_is_well_formed() -> None:
    assert STRATEGIES, "demo must ship at least one strategy"
    names = [spec["name"] for spec in STRATEGIES]
    assert len(names) == len(set(names)), "strategy names must be unique"
    for spec in STRATEGIES:
        # Required, non-empty descriptive fields.
        for key in ("name", "category", "description", "client_facing_copy"):
            assert spec.get(key), f"strategy {spec.get('name')!r} missing {key}"
        # Category is one the demo declares valid.
        assert spec["category"] in STRATEGY_CATEGORIES
        # Round-trips through the real library schema (proves field types match).
        payload = StrategyLibraryIn(
            name=spec["name"],
            category=spec["category"],
            description=spec["description"],
            client_facing_copy=spec["client_facing_copy"],
            savings_method="amount_x_effective_rate",
        )
        assert payload.savings_method == "amount_x_effective_rate"


def test_client_catalog_is_well_formed() -> None:
    assert CLIENTS, "demo must ship at least one client"
    names = [spec["name"] for spec in CLIENTS]
    assert len(names) == len(set(names)), "client display names must be unique"
    canonical = set(CANONICAL_1040_FIELD_KEYS)
    for spec in CLIENTS:
        # Required keys present.
        for key in ("name", "filing_status", "state", "fields", "make_plan"):
            assert key in spec, f"client {spec.get('name')!r} missing {key}"
        assert spec["filing_status"] in _VALID_FILING_STATUSES
        assert isinstance(spec["state"], str) and len(spec["state"]) == 2
        assert isinstance(spec["make_plan"], bool)
        # Has at least one filed figure, and every figure is a CANONICAL 1040
        # field key the extraction service can map (else confirm would ignore it).
        assert spec["fields"], f"client {spec['name']!r} has no figures"
        for field_key, cents in spec["fields"].items():
            assert field_key in canonical, f"unknown 1040 field key {field_key!r}"
            assert isinstance(cents, int) and cents > 0
        # Figures round-trip through the field-correction schema (cents are ints).
        for cents in spec["fields"].values():
            assert CorrectFieldRequest(corrected_value_cents=cents).corrected_value_cents == cents


def test_client_field_catalog_is_a_cents_mapping() -> None:
    """The seeder's correction and quarterly paths consume fields as a mapping."""
    assert all(
        isinstance(spec["fields"], dict)
        and all(
            isinstance(key, str) and isinstance(value, int)
            for key, value in spec["fields"].items()
        )
        for spec in CLIENTS
    )


def test_planned_clients_drive_the_plan_year_services() -> None:
    """Every client flagged make_plan must produce figures the plan/strategy/
    quarterly services accept — and at least one client exercises a plan."""
    assert any(spec["make_plan"] for spec in CLIENTS)
    assert DEMO_PLAN_TAX_YEAR > DEMO_BASE_TAX_YEAR
    strategy_count = len(STRATEGIES)
    for idx, spec in enumerate(CLIENTS):
        # Base tax year payload is constructible for every client.
        ClientCreate(
            display_name=spec["name"],
            filing_status_default=spec["filing_status"],
            primary_state=spec["state"],
        )
        ClientTaxYearCreate(
            client_id="00000000-0000-0000-0000-000000000000",
            tax_year=DEMO_BASE_TAX_YEAR,
            role="base",
            filing_status=spec["filing_status"],
        )
        if not spec["make_plan"]:
            continue
        # The two strategies the seeder picks for this client are in range.
        picked = list(range(idx % 2, idx % 2 + 2))
        assert all(i < strategy_count for i in picked)
        AddClientStrategyRequest(
            strategy_id="00000000-0000-0000-0000-000000000000",
            disposition="recommended",
            amount_cents=2_000_000 + idx * 500_000,
            status_flag="use_next_year",
        )
        # Quarterly payload the seeder builds is valid (mirrors _seed_into).
        base_tax = max(spec["fields"].get("f1040.line25_withholding", 0) + 500_000, 1_000_000)
        prior_year_agi = sum(
            value for key, value in spec["fields"].items() if "withholding" not in key
        )
        req = ComputeQuarterlyRequest(
            projected_current_year_tax_cents=base_tax,
            prior_year_tax_cents=base_tax - 200_000,
            prior_year_agi_cents=prior_year_agi,
            annual_withholding_cents=spec["fields"].get("f1040.line25_withholding", 0),
            method="even",
        )
        assert len(req.period_income_cents) == 4  # engine indexes all four quarters
