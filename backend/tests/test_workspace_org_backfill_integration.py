"""Workspace-org backfill against migrated Postgres (task 33982835).

For every workspace with org_id NULL, bind it to its OWNER's Ops-Center org
ONLY when unambiguous: exactly one owner-role member (workspace_membership,
role='owner', not deleted) whose Ops-Center answer is exactly one org where
they are owner or admin. Ambiguous (no owner, 2+ owners, 0 or 2+ orgs) ->
leave NULL and list. Ops-Center unreachable -> skip, leave NULL. One guarded
transaction per workspace (UPDATE ... WHERE id = $1 AND org_id IS NULL,
exactly one row, else rollback); a non-NULL org_id is never overwritten.
Idempotent: a re-run is a no-op. Dry run reads and asks but writes nothing.

The Ops-Center answer is injected as ``ask_orgs`` (the real HTTP read is
pinned in test_ops_center_orgs.py); one test wires the real
control_plane.owner_admin_orgs behind an httpx.MockTransport. No network.
Skips unless TPO_TEST_OWNER_DATABASE_URL points at a migrated DB (the backfill
runs as the owner role: the app role's RLS cannot see other workspaces). All
subjects, orgs and hosts are fictional.

Red on base c68559b: app.services.org_backfill does not exist (ImportError).
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")
del asyncpg

from app.services.org_backfill import backfill_workspace_orgs  # noqa: E402

ORG_A = UUID("11111111-2222-4333-8444-555555555555")
ORG_B = UUID("22222222-3333-4444-8555-666666666666")


def _owner_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_OWNER_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_OWNER_DATABASE_URL not set")
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgres://")
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgresql://")
    return dsn


@pytest.fixture
async def session_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine(_owner_dsn(), poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _insert_workspace(
    factory: Any,
    *,
    workspace_id: UUID,
    org_id: UUID | None,
    owners: tuple[str, ...] = (),
    members: tuple[str, ...] = (),
    deleted_owners: tuple[str, ...] = (),
) -> None:
    async with factory() as session:
        await session.execute(
            text("INSERT INTO workspaces (id, name, org_id) VALUES (:id, :name, :org)"),
            {"id": str(workspace_id), "name": "Fictional Backfill Workspace", "org": str(org_id) if org_id else None},
        )
        for uid, role, deleted in (
            [(u, "owner", False) for u in owners]
            + [(u, "member", False) for u in members]
            + [(u, "owner", True) for u in deleted_owners]
        ):
            await session.execute(
                text(
                    "INSERT INTO workspace_membership "
                    "(id, user_uc_uid, workspace_id, workspace_name, role, deleted_at) "
                    "VALUES (gen_random_uuid(), :u, :w, :n, :r, "
                    "CASE WHEN :d THEN now() ELSE NULL END)"
                ),
                {
                    "u": uid,
                    "w": str(workspace_id),
                    "n": "Fictional Backfill Workspace",
                    "r": role,
                    "d": deleted,
                },
            )
        await session.commit()


async def _org_of(factory: Any, workspace_id: UUID) -> str | None:
    async with factory() as session:
        value = await session.scalar(
            text("SELECT org_id::text FROM workspaces WHERE id = :id"), {"id": str(workspace_id)}
        )
    return None if value is None else str(value)


def _ask(answers: dict[str, list[str] | None]):  # type: ignore[no-untyped-def]
    asked: list[str] = []

    async def ask_orgs(uc_uid: str) -> list[str] | None:
        asked.append(uc_uid)
        return answers.get(uc_uid)

    ask_orgs.asked = asked  # type: ignore[attr-defined]
    return ask_orgs


async def test_unbound_with_one_owner_org_is_bound(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(
        session_factory, _ask({owner: [str(ORG_A)]})
    )
    assert [str(w) for w in result.bound] == [str(ws)]
    assert result.ambiguous == [] and result.skipped == []
    assert await _org_of(session_factory, ws) == str(ORG_A)


async def test_two_owner_orgs_left_null(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(
        session_factory, _ask({owner: [str(ORG_A), str(ORG_B)]})
    )
    assert result.bound == []
    assert [str(w) for w in result.ambiguous] == [str(ws)]
    assert await _org_of(session_factory, ws) is None


async def test_zero_owner_orgs_left_null(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(session_factory, _ask({owner: []}))
    assert result.bound == []
    assert [str(w) for w in result.ambiguous] == [str(ws)]
    assert await _org_of(session_factory, ws) is None


async def test_no_owner_member_left_null(session_factory: Any) -> None:
    ws = uuid4()
    member = f"fictional-backfill-member-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, members=(member,))
    ask = _ask({})
    result = await backfill_workspace_orgs(session_factory, ask)
    assert [str(w) for w in result.ambiguous] == [str(ws)]
    assert ask.asked == []  # nobody to ask
    assert await _org_of(session_factory, ws) is None


async def test_two_owner_members_ambiguous(session_factory: Any) -> None:
    ws = uuid4()
    o1 = f"fictional-backfill-owner-a-{uuid4()}"
    o2 = f"fictional-backfill-owner-b-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(o1, o2))
    ask = _ask({o1: [str(ORG_A)], o2: [str(ORG_A)]})
    result = await backfill_workspace_orgs(session_factory, ask)
    assert [str(w) for w in result.ambiguous] == [str(ws)]
    assert ask.asked == []
    assert await _org_of(session_factory, ws) is None


async def test_deleted_owner_membership_ignored(session_factory: Any) -> None:
    ws = uuid4()
    live = f"fictional-backfill-live-{uuid4()}"
    gone = f"fictional-backfill-gone-{uuid4()}"
    await _insert_workspace(
        session_factory, workspace_id=ws, org_id=None, owners=(live,), deleted_owners=(gone,)
    )
    result = await backfill_workspace_orgs(
        session_factory, _ask({live: [str(ORG_A)]})
    )
    assert [str(w) for w in result.bound] == [str(ws)]
    assert await _org_of(session_factory, ws) == str(ORG_A)


async def test_already_bound_untouched(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=ORG_B, owners=(owner,))
    ask = _ask({owner: [str(ORG_A)]})
    result = await backfill_workspace_orgs(session_factory, ask)
    assert result.bound == [] and result.ambiguous == [] and result.skipped == []
    assert ask.asked == []  # never even asked
    assert await _org_of(session_factory, ws) == str(ORG_B)


async def test_rerun_is_a_noop(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))
    ask = _ask({owner: [str(ORG_A)]})
    first = await backfill_workspace_orgs(session_factory, ask)
    assert [str(w) for w in first.bound] == [str(ws)]
    second = await backfill_workspace_orgs(session_factory, ask)
    assert second.bound == [] and second.ambiguous == [] and second.skipped == []
    assert await _org_of(session_factory, ws) == str(ORG_A)


async def test_dry_run_changes_nothing(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))
    ask = _ask({owner: [str(ORG_A)]})
    result = await backfill_workspace_orgs(session_factory, ask, dry_run=True)
    assert [str(w) for w in result.bound] == [str(ws)]  # would bind
    assert await _org_of(session_factory, ws) is None  # but did not
    # and the real run afterwards still binds it
    real = await backfill_workspace_orgs(session_factory, ask)
    assert [str(w) for w in real.bound] == [str(ws)]
    assert await _org_of(session_factory, ws) == str(ORG_A)


async def test_ops_center_failure_skips_and_leaves_null(session_factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(session_factory, _ask({owner: None}))
    assert result.bound == []
    assert [str(w) for w in result.skipped] == [str(ws)]
    assert await _org_of(session_factory, ws) is None


async def test_real_owner_admin_orgs_behind_fake_transport(session_factory: Any, monkeypatch):  # type: ignore[no-untyped-def]
    """End to end: the service wired to the real Ops-Center read (MockTransport)."""
    import httpx

    from app.core.config import Settings
    from app.integrations import control_plane

    ws = uuid4()
    owner = f"fictional-backfill-e2e-{uuid4()}"
    await _insert_workspace(session_factory, workspace_id=ws, org_id=None, owners=(owner,))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://ops-center.example.com/api/v1/orgs?")
        assert request.url.params["uc_uid"] == owner
        return httpx.Response(
            200, json={"orgs": [{"org_id": str(ORG_A), "role": "owner"}]}
        )

    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(control_plane.httpx, "AsyncClient", factory)
    settings = Settings(OPS_CENTER_URL="https://ops-center.example.com")

    async def ask_orgs(uc_uid: str) -> list[str] | None:
        return await control_plane.owner_admin_orgs(
            bearer="fictional.operator.bearer", uc_uid=uc_uid, settings=settings
        )

    result = await backfill_workspace_orgs(session_factory, ask_orgs)
    assert [str(w) for w in result.bound] == [str(ws)]
    assert await _org_of(session_factory, ws) == str(ORG_A)
