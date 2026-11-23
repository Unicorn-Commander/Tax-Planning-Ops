"""T1 (ea4d1636): Accounting-Ops links are UUID-typed and verified at set-time.

A link to an AO workspace used to be a free-form string stored unvalidated,
and the pulls ran with TPO's own service token — which AO floors to viewer on
ANY workspace — so pointing a link at another tenant's AO workspace read that
tenant's P&L / tax documents through TPO (confused deputy), and '../' in the
id reached other AO routes.

Pinned here: non-UUID ids are 422 (schema), a link the caller's own bearer
cannot see on AO is refused (403) with nothing stored, a verified link stores
provenance, and an unverified (legacy) link NEVER calls AO. Fake AO via
httpx.MockTransport; no network. All people/workspaces are fictional.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.clients import AccountingOpsLinkIn, link_accounting_ops
from app.api.entities import post_entity
from app.core.config import Settings
from app.integrations import accounting_ops
from app.integrations.accounting_ops import (
    AccountingOpsWorkspaceNotFoundError,
    fetch_pl,
    fetch_tax_documents,
    verify_caller_workspace_access,
)
from app.models.client import Client
from app.models.tax_year import ClientTaxYear
from app.schemas.auth import AuthContext
from app.schemas.entity import BusinessEntityIn
from app.services import source_documents
from app.services.source_documents import (
    set_accounting_ops_link,
    sync_tax_documents_from_accounting_ops,
)

AO_URL = "https://accounting-ops.example.com"
WS = str(uuid4())
BEARER = "fictional.advisor.bearer"  # noqa: S105
SERVICE_TOKEN = "tpo.service.token"  # noqa: S105
# A real end-user principal (carries uc_uid, no service azp/client_id).
USER_CLAIMS: dict[str, Any] = {"uc_uid": "fictional-advisor", "sub": "fictional-advisor"}
# An M2M-shaped token: middleware stamps it as a user bearer, but it has no
# uc_uid and its azp is a known service client, so it must never verify a link.
M2M_CLAIMS: dict[str, Any] = {"azp": "tax-planning-ops", "sub": "svc"}  # noqa: S105


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ACCOUNTING_OPS_ENABLED": True,
        "ACCOUNTING_OPS_URL": AO_URL,
        "ACCOUNTING_OPS_SERVICE_TOKEN": SERVICE_TOKEN,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake_ao(monkeypatch: pytest.MonkeyPatch):
    """Handler-driven fake AO; returns a factory giving the captured requests."""
    seen: list[httpx.Request] = []

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        real = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(recording)
            return real(*args, **kwargs)

        monkeypatch.setattr(accounting_ops.httpx, "AsyncClient", factory)
        return seen

    return install


# --- (a) schema: ids are UUIDs, anything else is a 422 ------------------------


def test_link_in_rejects_non_uuid_ids() -> None:
    for bad in ("../x", "ws-1", "1/../2", ""):
        with pytest.raises(ValidationError):
            AccountingOpsLinkIn(accounting_ops_workspace_id=bad)
    with pytest.raises(ValidationError):
        AccountingOpsLinkIn(accounting_ops_workspace_id=WS, accounting_ops_entity_id="nope")
    ok = AccountingOpsLinkIn(accounting_ops_workspace_id=WS)
    assert ok.accounting_ops_workspace_id == UUID(WS)


def test_entity_in_rejects_non_uuid_ao_ids() -> None:
    with pytest.raises(ValidationError):
        BusinessEntityIn(kind="schedule_c", accounting_ops_workspace_id="../x")
    with pytest.raises(ValidationError):
        BusinessEntityIn(kind="schedule_c", accounting_ops_entity_id="not-a-uuid")


# --- verify_caller_workspace_access: the caller's bearer, fail closed ---------


@pytest.mark.asyncio
async def test_verify_uses_caller_bearer_and_canonical_url(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(200, json={"id": WS}))
    assert await verify_caller_workspace_access(_settings(), WS, BEARER) is True
    assert len(seen) == 1
    assert str(seen[0].url) == f"{AO_URL}/api/workspaces/{WS}"
    assert seen[0].headers["Authorization"] == f"Bearer {BEARER}"
    assert SERVICE_TOKEN not in seen[0].headers["Authorization"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 404, 500])
async def test_verify_refuses_non_200(fake_ao, status_code: int) -> None:
    seen = fake_ao(lambda r: httpx.Response(status_code))
    assert await verify_caller_workspace_access(_settings(), WS, BEARER) is False
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_verify_without_bearer_never_calls(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(200))
    assert await verify_caller_workspace_access(_settings(), WS, None) is False
    assert seen == []


@pytest.mark.asyncio
async def test_verify_m2m_principal_never_calls_ao(fake_ao) -> None:
    # A service/M2M token (no uc_uid, azp is a known service client) must not
    # verify a link: AO is never contacted, even with a bearer present.
    seen = fake_ao(lambda r: httpx.Response(200))
    assert await verify_caller_workspace_access(_settings(), WS, BEARER, M2M_CLAIMS) is False
    assert seen == []


@pytest.mark.asyncio
async def test_verify_user_principal_still_calls_ao(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(200, json={"id": WS}))
    assert await verify_caller_workspace_access(_settings(), WS, BEARER, USER_CLAIMS) is True
    assert len(seen) == 1


# --- (b) set-link: verified stores provenance; refused stores nothing ---------


class _FakeClient:
    def __init__(self) -> None:
        self.id = uuid4()
        self.accounting_ops_workspace_id: str | None = None
        self.accounting_ops_entity_id: str | None = None
        self.accounting_ops_linked_at = None
        self.accounting_ops_linked_by: str | None = None


class _FakeDb:
    def __init__(self, *rows: Any) -> None:
        self.rows = {type(r): r for r in rows}
        self.flushed = False

    async def get(self, model: Any, pk: Any) -> Any:
        del pk
        return self.rows.get(model)

    async def flush(self) -> None:
        self.flushed = True


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(source_documents, "append_audit_event", _noop)


@pytest.mark.asyncio
async def test_set_link_refused_stores_nothing(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(403))
    client = _FakeClient()
    db = _FakeDb(client)
    db.rows[Client] = client
    with pytest.raises(PermissionError):
        await set_accounting_ops_link(
            db,
            workspace_id=uuid4(),
            actor_uc_uid="fictional-advisor",
            client_id=client.id,
            accounting_ops_workspace_id=UUID(WS),
            accounting_ops_entity_id=None,
            caller_bearer=BEARER,
            caller_claims=USER_CLAIMS,
            settings=_settings(),
        )
    assert client.accounting_ops_workspace_id is None
    assert client.accounting_ops_linked_at is None
    assert client.accounting_ops_linked_by is None
    assert not db.flushed
    assert len(seen) == 1  # asked AO as the caller, once


@pytest.mark.asyncio
async def test_set_link_verified_stores_provenance(fake_ao) -> None:
    fake_ao(lambda r: httpx.Response(200, json={"id": WS}))
    client = _FakeClient()
    db = _FakeDb(client)
    db.rows[Client] = client
    out = await set_accounting_ops_link(
        db,
        workspace_id=uuid4(),
        actor_uc_uid="fictional-advisor",
        client_id=client.id,
        accounting_ops_workspace_id=UUID(WS),
        accounting_ops_entity_id=None,
        caller_bearer=BEARER,
        caller_claims=USER_CLAIMS,
        settings=_settings(),
    )
    assert client.accounting_ops_workspace_id == WS
    assert client.accounting_ops_linked_at is not None
    assert client.accounting_ops_linked_by == "fictional-advisor"
    assert out["accounting_ops_workspace_id"] == WS


@pytest.mark.asyncio
async def test_unlink_clears_link_and_provenance(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(200))
    client = _FakeClient()
    client.accounting_ops_workspace_id = WS
    client.accounting_ops_linked_at = "2026-01-01T00:00:00+00:00"
    client.accounting_ops_linked_by = "fictional-advisor"
    db = _FakeDb(client)
    db.rows[Client] = client
    await set_accounting_ops_link(
        db,
        workspace_id=uuid4(),
        actor_uc_uid="fictional-advisor",
        client_id=client.id,
        accounting_ops_workspace_id=None,
        accounting_ops_entity_id=None,
        caller_bearer=BEARER,
        caller_claims=USER_CLAIMS,
        settings=_settings(),
    )
    assert client.accounting_ops_workspace_id is None
    assert client.accounting_ops_linked_at is None
    assert client.accounting_ops_linked_by is None
    assert seen == []  # unlink asks AO nothing


# --- (c) unverified links never call AO ---------------------------------------


@pytest.mark.asyncio
async def test_legacy_unverified_link_never_calls_ao(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(500))
    client = _FakeClient()
    client.accounting_ops_workspace_id = WS  # legacy row: id but no provenance
    cty = SimpleNamespace(
        id=uuid4(), client_id=client.id, tax_year=2025,
        source_documents=[], source_documents_synced_at=None,
    )
    db = _FakeDb(client, cty)
    db.rows[ClientTaxYear] = cty
    db.rows[Client] = client
    with pytest.raises(ValueError):
        await sync_tax_documents_from_accounting_ops(
            db,
            workspace_id=uuid4(),
            actor_uc_uid="fictional-advisor",
            tax_year_id=cty.id,
            settings=_settings(),
        )
    assert seen == []


@pytest.mark.asyncio
async def test_fetch_pl_refuses_non_uuid_id_without_http(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(500))
    with pytest.raises(AccountingOpsWorkspaceNotFoundError):
        await fetch_pl("../x", _settings())
    with pytest.raises(AccountingOpsWorkspaceNotFoundError):
        await fetch_tax_documents("ws-1", _settings())
    assert seen == []


@pytest.mark.asyncio
async def test_fetch_pl_builds_url_from_canonical_uuid(fake_ao) -> None:
    seen = fake_ao(lambda r: httpx.Response(200, json={"net_income": "100.00"}))
    summary = await fetch_pl(WS.upper(), _settings())
    assert summary.net_income_cents == 10_000
    assert str(seen[0].url).startswith(f"{AO_URL}/api/workspaces/{WS}/reports/pl")


# --- route level: 403 with the exact message, nothing stored ------------------


def _ctx() -> AuthContext:
    ws = uuid4()
    return AuthContext(
        claims=dict(USER_CLAIMS), uc_uid="fictional-advisor", workspace_id=ws,
        authorized_workspace_ids={ws}, scopes={"taxplan:advisor"},
    )


@pytest.mark.asyncio
async def test_link_route_403_for_unvisible_workspace(fake_ao) -> None:
    fake_ao(lambda r: httpx.Response(404))
    client = _FakeClient()
    db = _FakeDb(client)
    db.rows[Client] = client
    with pytest.raises(HTTPException) as exc:
        await link_accounting_ops(
            client.id,
            AccountingOpsLinkIn(accounting_ops_workspace_id=UUID(WS)),
            _ctx(),
            db,
            _settings(),
            BEARER,
        )
    assert exc.value.status_code == 403
    assert "not a member of that Accounting-Ops workspace" in exc.value.detail
    assert client.accounting_ops_workspace_id is None


@pytest.mark.asyncio
async def test_entity_route_403_for_unvisible_workspace(fake_ao) -> None:
    fake_ao(lambda r: httpx.Response(403))
    with pytest.raises(HTTPException) as exc:
        await post_entity(
            uuid4(),
            BusinessEntityIn(kind="schedule_c", accounting_ops_workspace_id=UUID(WS)),
            _ctx(),
            _FakeDb(),
            _settings(),
            BEARER,
        )
    assert exc.value.status_code == 403
    assert "not a member of that Accounting-Ops workspace" in exc.value.detail


def _m2m_ctx() -> AuthContext:
    ws = uuid4()
    return AuthContext(
        claims=dict(M2M_CLAIMS), uc_uid="svc", workspace_id=ws,
        authorized_workspace_ids={ws}, scopes={"taxplan:advisor"},
    )


@pytest.mark.asyncio
async def test_link_route_m2m_principal_cannot_verify(fake_ao) -> None:
    # An M2M-shaped token (middleware treats it as a user bearer) must not be
    # able to verify a link: refused 403 and AO is never called.
    seen = fake_ao(lambda r: httpx.Response(200))
    client = _FakeClient()
    db = _FakeDb(client)
    db.rows[Client] = client
    with pytest.raises(HTTPException) as exc:
        await link_accounting_ops(
            client.id,
            AccountingOpsLinkIn(accounting_ops_workspace_id=UUID(WS)),
            _m2m_ctx(),
            db,
            _settings(),
            BEARER,
        )
    assert exc.value.status_code == 403
    assert client.accounting_ops_workspace_id is None
    assert seen == []


# --- schema: link provenance is exposed for the UI ----------------------------


def test_entity_out_exposes_linked_at() -> None:
    from app.schemas.entity import BusinessEntityOut

    fields = BusinessEntityOut.model_fields
    assert "accounting_ops_linked_at" in fields
    unverified = BusinessEntityOut(
        id=uuid4(), workspace_id=uuid4(), client_tax_year_id=uuid4(),
        kind="schedule_c", accounting_ops_workspace_id=WS,
    )
    assert unverified.accounting_ops_linked_at is None
