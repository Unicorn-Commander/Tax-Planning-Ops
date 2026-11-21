"""Workspace-org backfill against migrated Postgres (task 33982835, round 2).

The backfill VALIDATES AND APPLIES an OPERATOR-SUPPLIED mapping file
(workspace_id -> org_id, produced by the Ops-Center owner); it never asks
Ops-Center anything (Ops-Center serves no endpoint that answers for other
users' orgs with an operator credential). Live checks are what Tax owns:
the workspace exists, its org_id is NULL, it has an owner-role member
(workspace_membership, role='owner', not deleted), the org_id is a canonical
UUID, and no workspace is listed twice. Anything invalid is refused, left
NULL and listed with a reason. The Ops-Center side (org exists, holds
tax_ops_access, the owner is a member) is TRUSTED from the mapping file.
Each bind is one guarded transaction (UPDATE ... WHERE id = $1 AND
org_id IS NULL, exactly one row, else rollback); a non-NULL org_id is never
overwritten. Idempotent: a re-run is a no-op. Dry run validates but writes
nothing. The DB is shared with the other integration files, so every
assertion is scoped to the workspace under test and each test deletes its
own rows. All subjects, orgs and hosts are fictional.

Red on 275749d: app.services.org_backfill has no MappingRow/Refusal/
load_mapping and backfill_workspace_orgs does not take mapping rows yet.
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

from app.services.org_backfill import (  # noqa: E402
    BackfillResult,
    MappingRow,
    backfill_workspace_orgs,
)

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
    the helper below so the shared test DB stays clean."""
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


def _outcome(result: BackfillResult, workspace_id: UUID) -> str | None:
    """"bound", the refusal reason for that workspace, or None if unlisted."""
    if workspace_id in result.bound:
        return "bound"
    reasons = [r.reason for r in result.refused if r.ref == str(workspace_id)]
    if len(reasons) > 1:
        return f"refused {len(reasons)}x: {reasons[0]}"
    return reasons[0] if reasons else None


def _row(workspace_id: UUID, org_id: str = str(ORG_A)) -> MappingRow:
    return MappingRow(workspace_id=workspace_id, org_id=org_id, ref="test")


async def test_valid_mapping_binds(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, [_row(ws)])
    assert _outcome(result, ws) == "bound"
    assert await _org_of(factory, ws) == str(ORG_A)


async def test_unknown_workspace_refused_and_listed(factory: Any) -> None:
    missing = uuid4()
    result = await backfill_workspace_orgs(factory, [_row(missing)])
    assert _outcome(result, missing) == "workspace not found"
    assert missing not in result.bound


async def test_already_bound_refused_and_never_overwritten(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=ORG_B, owners=(owner,))
    result = await backfill_workspace_orgs(factory, [_row(ws, str(ORG_A))])
    assert _outcome(result, ws) == "workspace already bound"
    assert await _org_of(factory, ws) == str(ORG_B)


@pytest.mark.parametrize(
    "bad_org",
    [
        pytest.param("not-a-uuid", id="not-a-uuid"),
        pytest.param("11111111-2222-4333-8444-55555555555", id="too-short"),
        pytest.param("11111111222243338444 5555555555555", id="not-hex-dashes"),
        pytest.param("11111111-2222-4333-8444-AAAAAAAAAAAA", id="uppercase-not-canonical"),
        pytest.param("", id="empty"),
    ],
)
async def test_malformed_org_id_refused(factory: Any, bad_org: str) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, [_row(ws, bad_org)])
    assert _outcome(result, ws) == "org_id is not a canonical uuid"
    assert await _org_of(factory, ws) is None


async def test_duplicate_workspace_refused_left_null(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, [_row(ws), _row(ws)])
    assert _outcome(result, ws) == "refused 2x: workspace listed more than once in the mapping"
    assert await _org_of(factory, ws) is None


async def test_no_owner_member_refused(factory: Any) -> None:
    ws = uuid4()
    member = f"fictional-backfill-member-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, members=(member,))
    result = await backfill_workspace_orgs(factory, [_row(ws)])
    assert _outcome(result, ws) == "no owner member"
    assert await _org_of(factory, ws) is None


async def test_deleted_owner_membership_not_an_owner(factory: Any) -> None:
    ws = uuid4()
    gone = f"fictional-backfill-gone-{uuid4()}"
    await _insert_workspace(
        factory, workspace_id=ws, org_id=None, deleted_owners=(gone,)
    )
    result = await backfill_workspace_orgs(factory, [_row(ws)])
    assert _outcome(result, ws) == "no owner member"
    assert await _org_of(factory, ws) is None


async def test_dry_run_changes_nothing(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    result = await backfill_workspace_orgs(factory, [_row(ws)], dry_run=True)
    assert _outcome(result, ws) == "bound"  # would bind
    assert await _org_of(factory, ws) is None  # but did not
    # and the real run afterwards still binds it
    real = await backfill_workspace_orgs(factory, [_row(ws)])
    assert _outcome(real, ws) == "bound"
    assert await _org_of(factory, ws) == str(ORG_A)


async def test_rerun_is_a_noop(factory: Any) -> None:
    ws = uuid4()
    owner = f"fictional-backfill-owner-{uuid4()}"
    await _insert_workspace(factory, workspace_id=ws, org_id=None, owners=(owner,))
    first = await backfill_workspace_orgs(factory, [_row(ws)])
    assert _outcome(first, ws) == "bound"
    second = await backfill_workspace_orgs(factory, [_row(ws)])
    assert _outcome(second, ws) == "workspace already bound"  # listed, not bound again
    assert await _org_of(factory, ws) == str(ORG_A)  # unchanged
