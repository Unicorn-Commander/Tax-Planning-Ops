"""Ops-Center tax_ops_access check (app.integrations.control_plane).

A fake Ops-Center (httpx.MockTransport) answers each case; no network. The
caller's own bearer is forwarded. Allowed ONLY on 200 with authorized == true;
every other answer fails closed. All subjects, orgs and hosts are fictional.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.integrations import control_plane

OPS_CENTER = "https://ops-center.example.com"
BEARER = "fictional.user.bearer"  # noqa: S105
ORG = "11111111-2222-4333-8444-555555555555"
ORG_B = "22222222-3333-4444-8555-666666666666"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ENTITLEMENT_CHECK_ENABLED": True,
        "OPS_CENTER_URL": OPS_CENTER,
    }
    values.update(overrides)
    return Settings(**values)


def _body(authorized: bool) -> dict[str, Any]:
    return {
        "org_id": ORG if authorized else None,
        "org_name": "Fictional Birch Advisors",
        "display_name": "Fictional Birch Advisors",
        "slug": "fictional-birch",
        "tier": "professional",
        "role": "member",
        "entitlements": ["tax_ops_access"] if authorized else [],
        "authorized": authorized,
    }


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # getattr: on a base without the cache the tests still run and fail on
    # behaviour, not in setup.
    getattr(control_plane, "clear_entitlement_cache", lambda: None)()


@pytest.fixture
def fake_ops_center(monkeypatch: pytest.MonkeyPatch):
    """Install a handler-driven fake Ops-Center; returns the captured requests."""
    seen: list[httpx.Request] = []

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        real = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(recording)
            return real(*args, **kwargs)

        monkeypatch.setattr(control_plane.httpx, "AsyncClient", factory)
        return seen

    return install


async def _check(settings: Settings | None = None, **kwargs: Any) -> bool:
    return await control_plane.check_tax_ops_access(
        bearer=kwargs.pop("bearer", BEARER),
        sub=kwargs.pop("sub", "fictional-sub-1"),
        settings=settings or _settings(),
        **kwargs,
    )


async def test_flag_off_allows_without_calling(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: httpx.Response(500))
    assert await _check(_settings(ENTITLEMENT_CHECK_ENABLED=False, OPS_CENTER_URL="")) is True
    assert seen == []


async def test_authorized_true_allows_and_forwards_bearer(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    assert await _check() is True
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == f"{OPS_CENTER}/api/v1/entitlements?feature_key=tax_ops_access"
    assert req.headers["Authorization"] == f"Bearer {BEARER}"


async def test_org_claim_is_forwarded(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    assert await _check(org_id=ORG) is True
    assert seen[0].url.params["org_id"] == ORG
    assert seen[0].url.params["feature_key"] == "tax_ops_access"


async def test_answer_for_another_org_refuses(fake_ops_center) -> None:
    """R2-1: asked for org B, a 200 authorized=true answer for org A is a refusal."""
    seen = fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    assert await _check(org_id=ORG_B) is False
    assert seen[0].url.params["org_id"] == ORG_B


async def test_answer_for_the_asked_org_allows(fake_ops_center) -> None:
    fake_ops_center(lambda r: httpx.Response(200, json={**_body(True), "org_id": ORG_B}))
    assert await _check(org_id=ORG_B) is True


async def test_tax_ops_org_returns_the_answered_org(fake_ops_center) -> None:
    fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    org = await control_plane.tax_ops_org(
        bearer=BEARER, sub="fictional-sub-1", settings=_settings()
    )
    assert org == ORG


@pytest.mark.parametrize(
    "org_id",
    [None, "", "not-a-uuid", "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE", 42],
    ids=["null", "empty", "not-a-uuid", "non-canonical", "not-a-string"],
)
async def test_authorized_without_a_usable_org_refuses(fake_ops_center, org_id) -> None:
    """R2-1: authorized=true with no org to bind the workspace to is a refusal."""
    fake_ops_center(lambda r: httpx.Response(200, json={**_body(True), "org_id": org_id}))
    assert await _check() is False


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda r: httpx.Response(200, json=_body(False)), id="authorized-false"),
        pytest.param(lambda r: httpx.Response(401, json={"detail": "x"}), id="401"),
        pytest.param(lambda r: httpx.Response(403, json={"detail": "x"}), id="403"),
        pytest.param(lambda r: httpx.Response(404), id="404"),
        pytest.param(
            lambda r: httpx.Response(
                503,
                json={"detail": "Organization entitlements are temporarily unavailable."},
            ),
            id="503",
        ),
        pytest.param(lambda r: httpx.Response(200, content=b"<html>"), id="malformed-json"),
        pytest.param(lambda r: httpx.Response(200, json=["authorized"]), id="not-an-object"),
        pytest.param(
            lambda r: httpx.Response(200, json={"org_id": ORG, "entitlements": []}),
            id="missing-authorized",
        ),
        pytest.param(
            lambda r: httpx.Response(200, json={**_body(True), "authorized": "true"}),
            id="authorized-not-bool",
        ),
        pytest.param(
            lambda r: httpx.Response(201, json=_body(True)), id="non-200-success"
        ),
    ],
)
async def test_every_other_answer_refuses(fake_ops_center, handler) -> None:
    fake_ops_center(handler)
    assert await _check() is False


async def test_timeout_refuses(fake_ops_center) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fictional timeout", request=request)

    fake_ops_center(handler)
    assert await _check() is False


async def test_connection_error_refuses(fake_ops_center) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fictional refused", request=request)

    fake_ops_center(handler)
    assert await _check() is False


async def test_empty_url_with_flag_on_refuses_without_calling(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    assert await _check(_settings(OPS_CENTER_URL="")) is False
    assert seen == []


async def test_missing_bearer_refuses_without_calling(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    assert await _check(bearer="") is False
    assert seen == []


async def test_timeout_is_short(fake_ops_center, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        captured["timeout"] = kwargs.get("timeout")
        kwargs["transport"] = httpx.MockTransport(
            lambda r: httpx.Response(200, json=_body(True))
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(control_plane.httpx, "AsyncClient", factory)
    assert await _check() is True
    assert captured["timeout"] is not None and captured["timeout"] <= 3.0


async def test_positive_answer_cached_per_sub_and_org(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: httpx.Response(200, json=_body(True)))
    assert await _check(sub="fictional-sub-a") is True
    assert await _check(sub="fictional-sub-a") is True
    assert len(seen) == 1
    # A different subject, or a different org for the same subject, asks again.
    assert await _check(sub="fictional-sub-b") is True
    assert await _check(sub="fictional-sub-a", org_id=ORG) is True
    assert len(seen) == 3


async def test_positive_cache_expires_within_60s(fake_ops_center, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(control_plane.time, "monotonic", lambda: clock[0])
    answers = iter([_body(True), _body(False)])
    seen = fake_ops_center(lambda r: httpx.Response(200, json=next(answers)))
    assert await _check() is True
    clock[0] += 59.0
    assert await _check() is True
    assert len(seen) == 1
    clock[0] += 2.0  # 61 s after the positive answer: must ask again
    assert await _check() is False
    assert len(seen) == 2


async def test_refusal_is_not_cached(fake_ops_center) -> None:
    answers = iter([_body(False), _body(True)])
    seen = fake_ops_center(lambda r: httpx.Response(200, json=next(answers)))
    assert await _check() is False
    # The org was just granted tax_ops_access: the next request sees it.
    assert await _check() is True
    assert len(seen) == 2


async def test_error_after_positive_does_not_serve_stale_after_ttl(
    fake_ops_center, monkeypatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(control_plane.time, "monotonic", lambda: clock[0])
    calls = iter([httpx.Response(200, json=_body(True)), httpx.Response(503)])
    fake_ops_center(lambda r: next(calls))
    assert await _check() is True
    clock[0] += 61.0
    assert await _check() is False


async def test_refusal_logged_once_with_status_never_token(
    fake_ops_center, caplog: pytest.LogCaptureFixture
) -> None:
    fake_ops_center(lambda r: httpx.Response(401, json={"detail": BEARER}))
    with caplog.at_level(logging.DEBUG, logger="tax_planning_ops.entitlement"):
        assert await _check() is False
    records = [r for r in caplog.records if r.name == "tax_planning_ops.entitlement"]
    assert len(records) == 1
    assert "401" in records[0].getMessage()
    assert BEARER not in caplog.text


def test_ops_center_url_setting_has_no_default() -> None:
    assert Settings(_env_file=None).OPS_CENTER_URL == ""


def test_startup_error_line_when_enabled_without_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="tax_planning_ops.entitlement"):
        control_plane.log_entitlement_config(_settings(OPS_CENTER_URL=""))
        control_plane.log_entitlement_config(_settings())
        control_plane.log_entitlement_config(
            _settings(ENTITLEMENT_CHECK_ENABLED=False, OPS_CENTER_URL="")
        )
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "OPS_CENTER_URL" in errors[0].getMessage()
