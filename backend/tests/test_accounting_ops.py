"""Accounting-Ops adapter — net-income extraction across P&L shapes + the
disabled/auth gating. No live AO; the HTTP paths are exercised via the service
integration tests on dogfood."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.integrations.accounting_ops import (
    AccountingOpsDisabledError,
    _get_federation_token,
    extract_net_income_cents,
    fetch_pl,
)


def test_extract_ao_contract_top_level_dollar_string() -> None:
    # AO's confirmed contract: top-level `net_income`, a dollar Decimal string.
    assert extract_net_income_cents({"net_income": "1234.56"}) == 123_456
    assert extract_net_income_cents({"net_income": "80000.00"}) == 8_000_000
    # A loss flows through with sign.
    assert extract_net_income_cents({"net_income": "-5000.00"}) == -500_000


def test_extract_prefers_cents_field_as_is() -> None:
    assert extract_net_income_cents({"net_income_cents": 1_234_500}) == 1_234_500


def test_extract_scales_dollar_float() -> None:
    assert extract_net_income_cents({"net_income": 12345.67}) == 1_234_567


def test_extract_parses_dollar_string() -> None:
    assert extract_net_income_cents({"net_profit": "$80,000.00"}) == 8_000_000


def test_extract_looks_into_nested_summary() -> None:
    # Integers are taken as cents (suite convention); nested under a wrapper key.
    payload = {"period": "2026-YTD", "summary": {"net_income_cents": 5_000_000}}
    assert extract_net_income_cents(payload) == 5_000_000


def test_extract_returns_none_when_absent() -> None:
    assert extract_net_income_cents({"revenue_cents": 100, "expenses_cents": 40}) is None


def test_extract_ignores_bool() -> None:
    assert extract_net_income_cents({"net_income": True}) is None


@pytest.mark.asyncio
async def test_fetch_pl_disabled_raises() -> None:
    settings = Settings(ACCOUNTING_OPS_ENABLED=False, ACCOUNTING_OPS_URL="")
    with pytest.raises(AccountingOpsDisabledError):
        await fetch_pl("ws-1", settings)


@pytest.mark.asyncio
async def test_fetch_pl_enabled_without_url_raises() -> None:
    settings = Settings(ACCOUNTING_OPS_ENABLED=True, ACCOUNTING_OPS_URL="")
    with pytest.raises(AccountingOpsDisabledError):
        await fetch_pl("ws-1", settings)


@pytest.mark.asyncio
async def test_static_service_token_short_circuits_mint_and_exchange() -> None:
    # The static override bypasses both the KC mint and the Brigade exchange
    # (no network) — used for the live handshake / testing.
    settings = Settings(
        ACCOUNTING_OPS_SERVICE_TOKEN="static-token",  # noqa: S106 - test fixture
        BRIGADE_TOKEN_URL="https://brigade.example/exchange",  # noqa: S106 - test fixture
    )
    assert await _get_federation_token(settings, "ws-uuid") == "static-token"
