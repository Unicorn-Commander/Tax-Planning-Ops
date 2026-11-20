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
runs as the owner role: the app role's RLS cannot see other workspaces). The
DB is shared with the other integration files, so every assertion is scoped
to the workspace under test and each test deletes its own rows. All subjects,
orgs and hosts are fictional.

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
async def factory():  # type: ignore[no-untyped-def]
    """Owner-role session factory; deletes workspaces/memberships created via
    the returned helper so the shared test DB stays clean."""
    engine = create_async_engine(_owner_dsn(), poolclass=NullPool)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    created: list[UUID] = []
    maker.created = created  # type: ignore[attr-defined]
    try:
        yield maker
    finally:
        async with maker() as session:
            ids = [str(w) for w in created]
            if ids:
                await session.execute(
                    text("DELETE FROM workspace_membership WHERE workspace_id = ANY(:ids)"),
                    {"ids": ids},
                )
                await session.execute(
                    text("DELETE FROM workspaces WHERE id = ANY(:ids)"), {"ids": ids}
                )
                await session.commit()
        await engine.dispose()


async def _insert_workspace(
    maker: Any,
    *,
    workspace_id: UUID,
    org_id: UUID | None,
    owners: tuple[str, ...] = (),
    members: tuple[str, ...] = (),
    deleted_owners: tuple[str, ...] = (),
) -> None:
    async with maker() as session:
        await session.execute(
            text("INSERT INTO workspaces (id, name, org_id) VALUES (:id, :name, :org)"),
            {
                "id": str(workspace_id),
                "name": "Fictional Backfill Workspace",
                "org": str(org_id) if org_id else None,
            },
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
    maker.created.append(workspace_id)  # type: ignore[attr-defined]


async def _org_of(maker: Any, workspace_id: UUID) -> str | None:
    async with maker() as session:
        value = await session.scalar(
            text("SELECT org_id::text FROM workspaces WHERE id = :id"),
            {"id": str(workspace_id)},
        )
    return None if value is None else str(value)


def _outcome(result: Any, workspace_id: UUID) -> str | None:
    for label in ("bound", "ambiguous", "skipped"):
        if workspace_id in getattr(result, label):
            return label
    return None


def _ask(answers: dict[str, list[str] | None]):  # type: ignore[no-untyped-def]
    asked: list[str] = []

    async def ask_orgs(uc_uid: str) -> list[str] | None:
        asked.append(uc_uid)
        return answers.get(uc_uid)

    ask_orgs.asked = asked  # type: ignore[attr-defined]
    return ask_orgs


async def test_unbound_with_one_owner_org_is_bound(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, _ask({owner: [str(ORG_A)]}))
    assert _outcome(result, ws) == "bound"
    assert await _org_of(factory, ws) == str(ORG_A)


async def test_two_owner_orgs_left_null(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(
        factory, _ask({owner: [str(ORG_A), str(ORG_B)]})
    )
    assert _outcome(result, ws) == "ambiguous"
    assert await _org_of(factory, ws) is None


async def test_zero_owner_orgs_left_null(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, _ask({owner: []}))
    assert _outcome(result, ws) == "ambiguous"
    assert await _org_of(factory, ws) is None


async def test_no_owner_member_left_null(factory: Any) -> None:
    ws = uuid4()
    member = f"fictional-backfill-member-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, members=(member,))
    ask = _ask({})
    result = await backfill_workspace_orgs(factory, ask)
    assert _outcome(result, ws) == "ambiguous"
    assert member not in ask.asked  # a member is not an owner to ask
    assert await _org_of(factory, ws) is None


async def test_two_owner_members_ambiguous(factory: Any) -> None:
    ws = uuid4()
    o1 = f"fictional-backfill-owner-a-{uuid4()}"
    o2 = f"fictional-backfill-owner-b-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(o1, o2))
    ask = _ask({o1: [str(ORG_A)], o2: [str(ORG_A)]})
    result = await backfill_workspace_orgs(factory, ask)
    assert _outcome(result, ws) == "ambiguous"
    assert o1 not in ask.asked and o2 not in ask.asked
    assert await _org_of(factory, ws) is None


async def test_deleted_owner_membership_ignored(factory: Any) -> None:
    ws = uuid4()
    live = f"fictional-backfill-live-{uuid4()}"
    gone = f"fictional-backfill-gone-{uuid4()}"
    await _insert_workspace(
        factory, workspace_id=ws, org_id=None, owners=(live,), deleted_owners=(gone,)
    )
    result = await backfill_workspace_orgs(factory, _ask({live: [str(ORG_A)]}))
    assert _outcome(result, ws) == "bound"
    assert await _org_of(factory, ws) == str(ORG_A)


async def test_already_bound_untouched(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=ORG_B, owners=(owner,))
    ask = _ask({owner: [str(ORG_A)]})
    result = await backfill_workspace_orgs(factory, ask)
    assert _outcome(result, ws) is None  # not even listed
    assert owner not in ask.asked  # never even asked
    assert await _org_of(factory, ws) == str(ORG_B)


async def test_rerun_is_a_noop(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    ask = _ask({owner: [str(ORG_A)]})
    first = await backfill_workspace_orgs(factory, ask)
    assert _outcome(first, ws) == "bound"
    second = await backfill_workspace_orgs(factory, ask)
    assert _outcome(second, ws) is None  # no longer unbound: nothing to do
    assert await _org_of(factory, ws) == str(ORG_A)


async def test_dry_run_changes_nothing(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    ask = _ask({owner: [str(ORG_A)]})
    result = await backfill_workspace_orgs(factory, ask, dry_run=True)
    assert _outcome(result, ws) == "bound"  # would bind
    assert await _org_of(factory, ws) is None  # but did not
    # and the real run afterwards still binds it
    real = await backfill_workspace_orgs(factory, ask)
    assert _outcome(real, ws) == "bound"
    assert await _org_of(factory, ws) == str(ORG_A)


async def test_ops_center_failure_skips_and_leaves_null(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, _ask({owner: None}))
    assert _outcome(result, ws) == "skipped"
    assert await _org_of(factory, ws) is None


async def test_real_owner_admin_orgs_behind_fake_transport(
    factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the service wired to the real Ops-Center read (MockTransport)."""
    import httpx

    from app.core.config import Settings
    from app.integrations import control_plane

    ws = uuid4()
    owner = f"fictional-backfill-e2e-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://ops-center.example.com/api/v1/orgs?")
        # Other rows may exist in the shared DB: answer empty for their owners,
        # exactly one org for the owner under test.
        if request.url.params["uc_uid"] == owner:
            return httpx.Response(
                200, json={"orgs": [{"org_id": str(ORG_A), "role": "owner"}]}
            )
        return httpx.Response(200, json={"orgs": []})

    real = httpx.AsyncClient

    def http_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(control_plane.httpx, "AsyncClient", http_factory)
    settings = Settings(OPS_CENTER_URL="https://ops-center.example.com")

    async def ask_orgs(uc_uid: str) -> list[str] | None:
        return await control_plane.owner_admin_orgs(
            bearer="fictional.operator.bearer", uc_uid=uc_uid, settings=settings
        )

    result = await backfill_workspace_orgs(factory, ask_orgs)
    assert _outcome(result, ws) == "bound"
    assert await _org_of(factory, ws) == str(ORG_A)
