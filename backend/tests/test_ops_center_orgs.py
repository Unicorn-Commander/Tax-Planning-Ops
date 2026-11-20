"""Ops-Center org-membership read for the workspace-org backfill.

``owner_admin_orgs`` asks Ops-Center (read-only, the same trust model as the
door in control_plane.tax_ops_org) which orgs a given user is owner or admin
of, for feature ``tax_ops_access``. A fake Ops-Center (httpx.MockTransport)
answers each case; no network. Allowed ONLY on 200 with a well-formed
``{"orgs": [{"org_id": <canonical uuid>, "role": <str>}, ...]}`` body; every
other answer (non-200, timeout, connection error, malformed JSON, missing or
non-list "orgs", a non-canonical org_id, a missing bearer or uc_uid, an unset
OPS_CENTER_URL) returns None: fail closed, the backfill then leaves the
workspace NULL. Roles other than owner/admin are filtered out; duplicates
collapse. All subjects, orgs and hosts are fictional.

Red on base c68559b: owner_admin_orgs does not exist yet (AttributeError) —
that missing read is what the backfill (task 33982835) needs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.integrations import control_plane

OPS_CENTER = "https://ops-center.example.com"
BEARER = "fictional.operator.bearer"  # noqa: S105
UC_UID = "fictional-owner-sub-1"
ORG_A = "11111111-2222-4333-8444-555555555555"
ORG_B = "22222222-3333-4444-8555-666666666666"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"OPS_CENTER_URL": OPS_CENTER}
    values.update(overrides)
    return Settings(**values)


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


async def _ask(settings: Settings | None = None, **kwargs: Any) -> list[str] | None:
    return await control_plane.owner_admin_orgs(
        bearer=kwargs.pop("bearer", BEARER),
        uc_uid=kwargs.pop("uc_uid", UC_UID),
        settings=settings or _settings(),
    )


def _orgs_body(entries: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"orgs": entries})


async def test_owner_and_admin_kept_member_filtered(fake_ops_center) -> None:
    seen = fake_ops_center(
        lambda r: _orgs_body(
            [
                {"org_id": ORG_A, "role": "owner"},
                {"org_id": ORG_B, "role": "admin"},
                {"org_id": "33333333-4444-4444-8555-777777777777", "role": "member"},
            ]
        )
    )
    orgs = await _ask()
    assert orgs == [ORG_A, ORG_B]
    assert len(seen) == 1
    url = seen[0].url
    assert str(url).startswith(f"{OPS_CENTER}/api/v1/orgs?")
    assert url.params["feature_key"] == "tax_ops_access"
    assert url.params["uc_uid"] == UC_UID
    assert seen[0].headers["authorization"] == f"Bearer {BEARER}"


async def test_duplicates_collapse(fake_ops_center) -> None:
    fake_ops_center(
        lambda r: _orgs_body(
            [{"org_id": ORG_A, "role": "owner"}, {"org_id": ORG_A, "role": "admin"}]
        )
    )
    assert await _ask() == [ORG_A]


async def test_empty_list_is_a_valid_answer(fake_ops_center) -> None:
    fake_ops_center(lambda r: _orgs_body([]))
    assert await _ask() == []


async def test_no_bearer_refuses_without_calling(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: _orgs_body([]))
    assert await _ask(bearer="") is None
    assert seen == []


async def test_no_uc_uid_refuses_without_calling(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: _orgs_body([]))
    assert await _ask(uc_uid="") is None
    assert seen == []


async def test_empty_url_refuses_without_calling(fake_ops_center) -> None:
    seen = fake_ops_center(lambda r: _orgs_body([]))
    assert await _ask(_settings(OPS_CENTER_URL="")) is None
    assert seen == []


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("fictional timeout", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda r: httpx.Response(401, json={"detail": "bad"}), id="401"),
        pytest.param(lambda r: httpx.Response(403, json={"detail": "nope"}), id="403"),
        pytest.param(lambda r: httpx.Response(503, json={"detail": "down"}), id="503"),
        pytest.param(lambda r: httpx.Response(200, content=b"<html>oops</html>"), id="malformed"),
        pytest.param(lambda r: httpx.Response(200, json={"orgs": "nope"}), id="orgs-not-a-list"),
        pytest.param(lambda r: httpx.Response(200, json={}), id="orgs-missing"),
        pytest.param(
            lambda r: _orgs_body([{"org_id": "not-a-uuid", "role": "owner"}]),
            id="org-id-not-canonical",
        ),
        pytest.param(
            lambda r: _orgs_body([{"org_id": ORG_A.upper(), "role": "owner"}]),
            id="org-id-not-lowercase-canonical",
        ),
        pytest.param(lambda r: _orgs_body([{"org_id": ORG_A}]), id="role-missing"),
        pytest.param(lambda r: _orgs_body(["just-a-string"]), id="entry-not-an-object"),
        pytest.param(_timeout, id="timeout"),
    ],
)
async def test_every_other_answer_fails_closed(fake_ops_center, handler) -> None:
    fake_ops_center(handler)
    assert await _ask() is None
