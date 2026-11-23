"""SSO callback redirect: tokens must travel in the URL fragment, not the query.

Fixtures are fictional. The Keycloak token endpoint is stubbed in-process, so no
network call is made. The route handler is exercised directly: it is the
RedirectResponse location that proxies, history and Referer headers would leak.
"""
from __future__ import annotations

import pytest

from app.api.auth import keycloak_callback
from tests.helpers.oauth_state import (
    FRONTEND,
    StateRequest,
    StubTokenClient,
    make_settings,
    run,
)

ACCESS_TOKEN = "fictional-access-token"  # noqa: S105
REFRESH_TOKEN = "fictional-refresh-token"  # noqa: S105




def test_callback_redirect_carries_tokens_in_fragment(
    stub_client: StubTokenClient,
    memory_store,
) -> None:
    state = "good-state"
    memory_store.add(state, "good-verifier")
    location = run(
        keycloak_callback(
            request=StateRequest(cookies={"tpo_oauth_state": state}),
            code="fictional-code",
            state=state,
            settings=make_settings(),
        )
    ).headers["location"]
    # Fragments never leave the browser, so they cannot be logged by any proxy.
    assert location.startswith(f"{FRONTEND}/auth/sso-callback#")
    query_part, fragment = location.split("#", 1)
    assert "?" not in query_part
    assert f"token={ACCESS_TOKEN}" in fragment
    assert f"refresh_token={REFRESH_TOKEN}" in fragment


def test_callback_redirect_without_refresh_token(
    stub_client: StubTokenClient,
    memory_store,
) -> None:
    stub_client.body = {
        "access_token": ACCESS_TOKEN,
        "expires_in": 300,
        "token_type": "Bearer",
    }
    state = "good-state-2"
    memory_store.add(state, "good-verifier-2")
    location = run(
        keycloak_callback(
            request=StateRequest({"tpo_oauth_state": state}),
            code="fictional-code",
            state=state,
            settings=make_settings(),
        )
    ).headers["location"]
    assert location == f"{FRONTEND}/auth/sso-callback#token={ACCESS_TOKEN}"
    assert "refresh_token" not in location
    assert "?" not in location


def test_callback_token_exchange_sends_pkce_verifier(
    stub_client: StubTokenClient,
    memory_store,
) -> None:
    """The token exchange is only allowed once the stored state is consumed,
    and it must carry the PKCE code_verifier (the S256 challenge was sent on
    the authorize request)."""
    state = "pkce-state"
    verifier = "pkce-verifier"
    memory_store.add(state, verifier)
    run(
        keycloak_callback(
            request=StateRequest({"tpo_oauth_state": state}),
            code="fictional-code",
            state=state,
            settings=make_settings(),
        )
    )
    assert len(stub_client.calls) == 1
    call = stub_client.calls[0]
    assert call["grant_type"] == "authorization_code"
    assert call["code"] == "fictional-code"
    assert call["code_verifier"] == verifier


def test_callback_token_endpoint_failure_is_401(
    stub_client: StubTokenClient,
    memory_store,
) -> None:
    from fastapi import HTTPException

    state = "fail-state"
    memory_store.add(state, "fail-verifier")
    stub_client.status_code = 400
    stub_client.body = {"error": "invalid_grant"}
    with pytest.raises(HTTPException) as exc:
        run(
            keycloak_callback(
                request=StateRequest({"tpo_oauth_state": state}),
                code="fictional-code",
                state=state,
                settings=make_settings(),
            )
        )
    assert exc.value.status_code == 401
    # The exchange ran (and failed): the state WAS valid, so reaching the
    # endpoint is correct. The failure is a Keycloak-side 400/401.
    assert len(stub_client.calls) == 1
