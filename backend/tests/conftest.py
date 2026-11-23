"""Suite-scoped fixtures.

Only the OAuth state / PKCE tests use these; the names are specific enough
that nothing else in the suite can collide with them. Declared here (the
suite root) so they register for every test file without any per-file import
tricks.
"""
from __future__ import annotations

import pytest

from tests.helpers.oauth_state import MemoryStateStore, StubTokenClient


@pytest.fixture(name="stub_client")
def stub_client(monkeypatch: pytest.MonkeyPatch) -> StubTokenClient:
    """Replace httpx.AsyncClient inside app.api.auth with a recording stub,
    so the Keycloak token endpoint is never reached (no network in tests)."""
    stub = StubTokenClient()
    monkeypatch.setattr("app.api.auth.httpx.AsyncClient", lambda **kw: stub)
    return stub


@pytest.fixture(name="memory_store")
def memory_store(monkeypatch: pytest.MonkeyPatch) -> MemoryStateStore:
    """Replace the DB-backed pop_oauth_state with an in-memory dict double,
    so the state tests never touch a database."""
    store = MemoryStateStore()
    monkeypatch.setattr("app.api.auth.pop_oauth_state", store.pop)
    return store
