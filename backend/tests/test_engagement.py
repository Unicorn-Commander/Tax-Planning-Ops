"""Advisory-fee engagement service tests (no live DB).

The fee-basis validator is a pure Pydantic check, and the upsert/get policy is
exercised against a tiny in-memory fake session that answers only the ``scalar``
queries those functions make (client-existence lookup, then the engagement row).
A real-Postgres/RLS path is covered the same way the rest of the suite gates it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.client import Client
from app.models.engagement import Engagement
from app.schemas.engagement import FeeIn
from app.services.engagement import get_engagement, upsert_engagement

WS = uuid4()
CLIENT_ID = uuid4()


# --------------------------------------------------------------------------- #
# Pure schema validation
# --------------------------------------------------------------------------- #
def test_fee_basis_accepts_known_bases() -> None:
    for basis in ("flat", "aum", "hourly", "value"):
        assert FeeIn(fee_cents=250_000, fee_basis=basis).fee_basis == basis


def test_fee_basis_defaults_to_flat() -> None:
    assert FeeIn(fee_cents=0).fee_basis == "flat"


def test_fee_basis_rejects_unknown_basis() -> None:
    with pytest.raises(ValidationError):
        FeeIn(fee_cents=250_000, fee_basis="percentage")


def test_fee_cents_is_passed_through_verbatim() -> None:
    # Operator-supplied integer cents — taken as-is, never derived.
    payload = FeeIn(fee_cents=1_234_567, fee_basis="value", fee_note="annual retainer")
    assert payload.fee_cents == 1_234_567
    assert payload.fee_note == "annual retainer"


# --------------------------------------------------------------------------- #
# A minimal async fake session (no DB).
# --------------------------------------------------------------------------- #
class _FakeSession:
    """Answers ``scalar`` from a FIFO queue and records ``add``; ``flush`` is a
    no-op. Just enough surface for the engagement service's upsert/get."""

    def __init__(self, scalar_results: list[Any]) -> None:
        self._scalars = list(scalar_results)
        self.added: list[Any] = []

    async def scalar(self, *_a: Any, **_k: Any) -> Any:
        return self._scalars.pop(0) if self._scalars else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _client() -> Client:
    return Client(id=CLIENT_ID, workspace_id=WS, display_name="Jordan Alvarez")


def _engagement(fee_cents: int, basis: str = "flat") -> Engagement:
    return Engagement(
        id=uuid4(),
        workspace_id=WS,
        client_id=CLIENT_ID,
        fee_cents=fee_cents,
        fee_basis=basis,
    )


# --------------------------------------------------------------------------- #
# get_engagement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_returns_none_when_unset() -> None:
    db = _FakeSession([None])  # no engagement row
    assert await get_engagement(db, client_id=CLIENT_ID) is None


@pytest.mark.asyncio
async def test_get_returns_existing_row() -> None:
    existing = _engagement(500_000, "aum")
    db = _FakeSession([existing])
    out = await get_engagement(db, client_id=CLIENT_ID)
    assert out is existing
    assert out.fee_cents == 500_000


# --------------------------------------------------------------------------- #
# upsert_engagement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_upsert_inserts_when_absent() -> None:
    db = _FakeSession([_client(), None])  # client exists, no engagement yet
    payload = FeeIn(fee_cents=300_000, fee_basis="flat", fee_note="2026 plan")
    out = await upsert_engagement(db, workspace_id=WS, client_id=CLIENT_ID, payload=payload)
    assert isinstance(out, Engagement)
    assert out in db.added  # a new row was added
    assert out.workspace_id == WS
    assert out.client_id == CLIENT_ID
    assert out.fee_cents == 300_000
    assert out.fee_basis == "flat"
    assert out.fee_note == "2026 plan"


@pytest.mark.asyncio
async def test_upsert_updates_existing_in_place() -> None:
    existing = _engagement(300_000, "flat")
    db = _FakeSession([_client(), existing])  # client exists, engagement exists
    payload = FeeIn(fee_cents=750_000, fee_basis="value", fee_note="raised")
    out = await upsert_engagement(db, workspace_id=WS, client_id=CLIENT_ID, payload=payload)
    assert out is existing  # same row mutated, not a new one
    assert out.fee_cents == 750_000
    assert out.fee_basis == "value"
    assert out.fee_note == "raised"


@pytest.mark.asyncio
async def test_upsert_raises_lookup_error_for_unknown_client() -> None:
    db = _FakeSession([None])  # client lookup misses
    payload = FeeIn(fee_cents=300_000)
    with pytest.raises(LookupError):
        await upsert_engagement(db, workspace_id=WS, client_id=CLIENT_ID, payload=payload)
    assert db.added == []  # nothing persisted on the error path
