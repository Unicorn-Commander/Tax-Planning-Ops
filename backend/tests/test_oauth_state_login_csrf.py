"""Login CSRF regression: the Keycloak callback must pair the query `state`
against the state cookie and consume the stored (state, PKCE verifier) row
BEFORE any token exchange. Missing, mismatched, replayed and expired states
all refuse with a 302 to the frontend landing page carrying ?auth_error=state;
a valid pair exchanges exactly once, with the code_verifier in the request.

The Keycloak token endpoint is stubbed in-process (no network); the oauth_state
table is an in-memory double (no database). Fixtures are fictional.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.api.auth import (
    STATE_COOKIE_HOST,
    STATE_TTL_SECONDS,
    create_oauth_state,
    keycloak_callback,
)
from tests.helpers.oauth_state import (
    FRONTEND,
    StateRequest,
    StubTokenClient,
    make_settings,
    run,
)

COOKIE = "tpo_oauth_state"  # plain name: FRONTEND is http://localhost (see helpers)
AUTH_ERROR = f"{FRONTEND}/?auth_error=state"


def _assert_error_redirect(response: Any, stub: StubTokenClient) -> None:
    assert response.status_code == 302
    assert response.headers["location"] == AUTH_ERROR
    # The state cookie must be cleared on the error path (Max-Age=0, no value).
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{COOKIE}=;" in set_cookie
    assert "Max-Age=0" in set_cookie
    # The contract: NO token exchange may happen on a refused state.
    assert stub.calls == []


class _ExpiredStore:
    """Store double where every stored row is already past its 1800 s TTL."""

    def __init__(self) -> None:
        self.records: dict[str, str] = {}

    def add(self, state: str, code_verifier: str) -> None:
        self.records[state] = code_verifier

    async def pop(self, state: str) -> str | None:
        if state not in self.records:
            return None
        # Emulates `expires_at <= now` on a row minted 1801 s ago: the record
        # exists but is past its deadline, so the real pop_oauth_state refuses.
        now = datetime.now(UTC)
        minted = now - timedelta(seconds=STATE_TTL_SECONDS + 1)
        assert minted + timedelta(seconds=STATE_TTL_SECONDS) <= now
        return None




def test_missing_state_is_refused_without_exchange(
    stub_client: StubTokenClient, memory_store
) -> None:
    memory_store.add("unused", "v")
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: "unused"}),
            code="attacker-code",
            state=None,
            settings=make_settings(),
        )
    )
    _assert_error_redirect(response, stub_client)


def test_missing_cookie_is_refused_without_exchange(
    stub_client: StubTokenClient, memory_store
) -> None:
    memory_store.add("s1", "v1")
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={}),
            code="attacker-code",
            state="s1",
            settings=make_settings(),
        )
    )
    _assert_error_redirect(response, stub_client)


def test_mismatched_state_cookie_is_refused_without_exchange(
    stub_client: StubTokenClient, memory_store
) -> None:
    """Login CSRF core: the attacker finishes their own login and hands the
    victim their code; the victim's browser sends ITS cookie. The two states
    must not pair, and the victim's code must never reach Keycloak. A stray
    callback must also NOT clear the victim's legitimate state cookie (their
    in-flight login survives; the cookie is cleared only after it is consumed
    or on an expired/unknown state)."""
    memory_store.add("victim-state", "victim-verifier")
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: "victim-state"}),
            code="attacker-code",
            state="attacker-state",
            settings=make_settings(),
        )
    )
    assert response.status_code == 302
    assert response.headers["location"] == AUTH_ERROR
    # Refused, with NO token exchange.
    assert stub_client.calls == []
    # Mismatch: the cookie is preserved (no Set-Cookie clearing it at all).
    assert response.headers.get("set-cookie", "") == ""
    # The victim's stored state must be untouched (they can log in again).
    assert "victim-state" in memory_store.records


def test_no_code_keycloak_error_redirect_is_refused_not_422(
    stub_client: StubTokenClient, memory_store
) -> None:
    """Keycloak error redirect (?error=access_denied&state=..., user denied
    the login): the state pairs, but there is no code to exchange. The
    callback must land the user on the frontend with ?auth_error=state,
    never return 422 JSON to a browser, never touch the token endpoint."""
    state = "denied-state"
    memory_store.add(state, "denied-verifier")
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code=None,
            state=state,
            settings=make_settings(),
        )
    )
    _assert_error_redirect(response, stub_client)
    # Nothing was exchanged, and the stored state is untouched: a denial must
    # not spend the victim's state (they can retry the login).
    assert state in memory_store.records


def test_no_code_and_no_state_is_refused_not_422(
    stub_client: StubTokenClient, memory_store
) -> None:
    """No code AND no state (a stray navigation to the callback URL): same
    safe landing, no 422, no exchange."""
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: "some-state"}),
            code=None,
            state=None,
            settings=make_settings(),
        )
    )
    _assert_error_redirect(response, stub_client)


def test_replayed_state_is_refused_without_exchange(
    stub_client: StubTokenClient, memory_store
) -> None:
    """A state that was already consumed (the login finished once) must not
    exchange a second time, even with the matching cookie still present."""
    state = "replay-state"
    memory_store.add(state, "replay-verifier")
    first = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="code-one",
            state=state,
            settings=make_settings(),
        )
    )
    assert first.status_code == 302
    assert len(stub_client.calls) == 1
    stub_client.calls.clear()
    second = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="code-one",
            state=state,
            settings=make_settings(),
        )
    )
    _assert_error_redirect(second, stub_client)


def test_unknown_state_with_cookie_is_refused_without_exchange(
    stub_client: StubTokenClient, memory_store
) -> None:
    """Cookie and query agree, but the server never minted that state (e.g. a
    cookie copied from another machine). No row, no exchange."""
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: "ghost"}),
            code="attacker-code",
            state="ghost",
            settings=make_settings(),
        )
    )
    _assert_error_redirect(response, stub_client)


def test_expired_state_is_refused_without_exchange(
    stub_client: StubTokenClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The store is a dict double here, so expiry is enforced by the clock:
    the double reports a row past its 1800 s TTL, and the same refusal path
    must fire. The DB path applies the identical `expires_at <= now` check on
    the real table."""
    store = _ExpiredStore()
    store.add("stale", "stale-verifier")
    monkeypatch.setattr("app.api.auth.pop_oauth_state", store.pop)
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: "stale"}),
            code="stale-code",
            state="stale",
            settings=make_settings(),
        )
    )
    _assert_error_redirect(response, stub_client)


def test_valid_state_pairs_and_exchanges_once(
    stub_client: StubTokenClient, memory_store
) -> None:
    state = "valid-state"
    verifier = "valid-verifier"
    memory_store.add(state, verifier)
    response = run(
        keycloak_callback(
            request=StateRequest(cookies={COOKIE: state}),
            code="honest-code",
            state=state,
            settings=make_settings(),
        )
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{FRONTEND}/auth/sso-callback#")
    assert f"token={stub_client.body['access_token']}" in location
    assert len(stub_client.calls) == 1
    call = stub_client.calls[0]
    assert call["code"] == "honest-code"
    assert call["code_verifier"] == verifier
    # The success redirect clears the state cookie (single use is done).
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{COOKIE}=;" in set_cookie and "Max-Age=0" in set_cookie
    # And the token-carrying Location must not be cacheable or leakable.
    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("referrer-policy") == "no-referrer"


def test_state_cookie_name_follows_public_url() -> None:
    from app.api.auth import STATE_COOKIE_PLAIN, _state_cookie_name

    assert _state_cookie_name(make_settings()) == STATE_COOKIE_PLAIN
    assert (
        _state_cookie_name(make_settings(FRONTEND_URL="https://tax.example.com"))
        == STATE_COOKIE_HOST
    )


def test_mint_prunes_expired_rows_before_storing_new_state() -> None:
    """Every mint sweeps rows already past expires_at + 1 h (the public
    /auth/keycloak must not let oauth_state grow without bound). The mint's
    FIRST statement is the prune DELETE, filtered on expires_at; the new row
    is stored afterwards. The real table effect (dead rows gone, fresh and
    consumed rows kept) is proven by the integration test
    test_mint_prunes_old_rows_keeps_fresh_and_spent."""

    class _FakeSession:
        def __init__(self) -> None:
            self.statements: list[object] = []
            self.added: list[object] = []

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            del exc
            return False

        def add(self, record: object) -> None:
            self.added.append(record)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def execute(self, stmt: object, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self.statements.append(stmt)
            return None

    session = _FakeSession()
    state, verifier = run(create_oauth_state(session))

    # Statement one is the prune sweep: a DELETE from oauth_state whose WHERE
    # filters on expires_at (the 1 h slack is a bound parameter, not literal).
    assert len(session.statements) == 1
    prune_sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "DELETE FROM oauth_state" in prune_sql
    assert "expires_at" in prune_sql
    # Then the mint stores exactly one fresh row.
    assert len(session.added) == 1
    record = session.added[0]
    assert record.state == state  # type: ignore[attr-defined]
    assert record.code_verifier == verifier  # type: ignore[attr-defined]


def test_login_mints_state_cookie_and_pkce_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /auth/keycloak login must mint a state + PKCE verifier, store the
    pair (so the callback can consume it), set the state cookie, and send the
    S256 challenge to Keycloak. The stored pair must round-trip: the verifier
    the callback later sends must be the one whose S256 challenge went out."""
    import hashlib

    from app.api.auth import _s256, keycloak_login

    # Replace the DB session with an in-memory double that records mints.
    mints: list[tuple[str, str]] = []

    class _FakeSession:
        def __init__(self) -> None:
            del self

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            del exc
            return False

        def add(self, record: object) -> None:
            state = getattr(record, "state", "")
            verifier = getattr(record, "code_verifier", "")
            mints.append((state, verifier))

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def execute(self, *args: object, **kwargs: object) -> None:
            # The per-mint prune sweep (delete of rows expired over an hour
            # ago) runs on this session; record nothing, delete nothing.
            del args, kwargs
            return None

    monkeypatch.setattr(
        "app.api.auth.async_session_maker", lambda: _FakeSession()
    )
    response = run(keycloak_login(settings=make_settings()))
    assert len(mints) == 1
    state, verifier = mints[0]
    # The state cookie carries the minted state (plain name for localhost).
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{COOKIE}={state}" in set_cookie
    lowered = set_cookie.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered
    # Plain name (localhost) must NOT be Secure; __Host- name would require it.
    assert "secure" not in lowered
    # The authorize redirect carries the state and the S256 challenge.
    location = response.headers["location"]
    from urllib.parse import parse_qs, urlparse

    params = parse_qs(urlparse(location).query)
    assert params["state"] == [state]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [_s256(verifier)]
    # Sanity: the challenge really is S256 of the stored verifier.
    assert _s256(verifier) == base64_url(
        hashlib.sha256(verifier.encode("ascii")).digest()
    )
    del hashlib


def base64_url(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
