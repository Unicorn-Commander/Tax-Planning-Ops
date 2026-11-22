"""Workspace member/invitation behavior against migrated Postgres RLS.

The normal test run skips this file unless ``TPO_TEST_DATABASE_URL`` points to
the migrated NOBYPASSRLS runtime database, matching test_rls_integration.py.
All subjects and workspace names are fictional and the transaction rolls back.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.db.session import bind_session_context  # noqa: E402
from app.services.member_tokens import hash_invitation_token  # noqa: E402
from app.services.members import (  # noqa: E402
    InvalidInvitationError,
    LastOwnerError,
    accept_invitation,
    add_member,
    create_invitation,
    list_members,
    remove_member,
)


def _async_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_DATABASE_URL not set")
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgres://")
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgresql://")
    return dsn


def _owner_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_OWNER_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_OWNER_DATABASE_URL not set")
    return dsn


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(_async_dsn(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
    await engine.dispose()


async def _seed_workspace_owner(
    owner_conn: asyncpg.Connection, workspace_id: str, owner_uc_uid: str
) -> None:
    """Commit the seed rows through the owner role (0024 removed the app role's
    direct INSERT on workspace_membership). The owner connection uses one
    implicit transaction per statement, so the rows are committed and visible
    to the app session's read-transaction snapshot."""
    await owner_conn.execute(
        "INSERT INTO workspaces (id, name) VALUES ($1, 'Fictional Cedar Tax Group') "
        "ON CONFLICT (id) DO NOTHING",
        workspace_id,
    )
    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'owner')",
        owner_uc_uid,
        workspace_id,
    )


@pytest.fixture
async def owner_conn():
    """The migration/owner role: since 0024 the app role may no longer write
    workspace_membership directly, so seed rows go through the owner connection
    (committed per statement, hence visible to the app session's
    read-transaction snapshot)."""
    conn = await asyncpg.connect(_owner_dsn())
    try:
        yield conn
    finally:
        await conn.close()


async def _add_second_owner(
    owner_conn: asyncpg.Connection, workspace_id: str, uid: str
) -> None:
    # A second owner seeded through the owner connection (the app role lost
    # direct INSERT in 0024); committed per statement so the app session's
    # read-transaction can see it. The caller keeps the GUCs bound to the
    # original owner (the actor for the following remove_member call).
    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'owner')",
        uid,
        workspace_id,
    )


@pytest.mark.asyncio
async def test_member_add_invite_accept_roster_and_last_owner_guard(
    db: AsyncSession,
    owner_conn: asyncpg.Connection,
) -> None:
    workspace_id = uuid4()
    owner = "fictional-owner-001"
    direct_member = "fictional-advisor-002"
    invited_member = "fictional-advisor-003"
    second_owner = "fictional-owner-004"
    await _seed_workspace_owner(owner_conn, str(workspace_id), owner)
    await bind_session_context(db, str(workspace_id), owner)

    added = await add_member(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=owner,
        member_uc_uid=direct_member,
    )
    assert added.user_uc_uid == direct_member
    assert added.role == "member"

    await bind_session_context(db, str(workspace_id), direct_member)
    with pytest.raises(PermissionError):
        await add_member(
            db,
            workspace_id=workspace_id,
            actor_uc_uid=direct_member,
            member_uc_uid="fictional-advisor-005",
        )

    await bind_session_context(db, str(workspace_id), owner)
    created = await create_invitation(
        db, workspace_id=workspace_id, actor_uc_uid=owner, invitee_uc_uid=invited_member
    )
    raw_token = str(created["invitation_token"])

    accepted = await accept_invitation(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=invited_member,
        raw_token=raw_token,
    )
    assert accepted.user_uc_uid == invited_member
    assert accepted.role == "member"
    # Re-bind the actor to the OWNER for the remainder of the test. accept_
    # invitation re-binds the session GUCs to the invitee (the accepting actor),
    # and every definer call re-derives the actor from current_uc_uid(); the
    # original owner must be the actor again before remove_member runs.
    await bind_session_context(db, str(workspace_id), owner)
    roster = await list_members(db, workspace_id=workspace_id, uc_uid=invited_member)
    assert {member.user_uc_uid for member in roster} == {
        owner,
        direct_member,
        invited_member,
    }
    assert all(member.role in {"owner", "member"} for member in roster)

    with pytest.raises(InvalidInvitationError):
        await accept_invitation(
            db,
            workspace_id=workspace_id,
            actor_uc_uid="fictional-advisor-006",
            raw_token=raw_token,
        )

    # The failed accept above aborts the app session's read-transaction (its
    # definer call RAISEd inside it), so roll it back and open a fresh one:
    # the definer functions' committed rows survive, and the exercise's own
    # writes still roll back at the end of the NEW transaction.
    await db.rollback()

    # Second owner via the owner connection (GUCs bound to `owner` below);
    # remove it, then prove the remaining owner cannot be removed as the last
    # owner.
    await _add_second_owner(owner_conn, str(workspace_id), second_owner)
    await bind_session_context(db, str(workspace_id), owner)
    await remove_member(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=owner,
        member_uc_uid=second_owner,
    )
    with pytest.raises(LastOwnerError):
        await remove_member(
            db,
            workspace_id=workspace_id,
            actor_uc_uid=owner,
            member_uc_uid=owner,
        )
    # The last-owner RAISE aborted the transaction again; roll back and start
    # a fresh one for the invitation-expiry step.
    await db.rollback()

    await bind_session_context(db, str(workspace_id), owner)
    expired = await create_invitation(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=owner,
        invitee_uc_uid="fictional-advisor-007",
    )
    await db.commit()
    await owner_conn.execute(
        "UPDATE workspace_invitation SET expires_at = now() - interval '1 minute' "
        "WHERE token_hash = $1",
        hash_invitation_token(str(expired["invitation_token"])),
    )
    await bind_session_context(db, str(workspace_id), owner)
    with pytest.raises(InvalidInvitationError):
        await accept_invitation(
            db,
            workspace_id=workspace_id,
            actor_uc_uid="fictional-advisor-007",
            raw_token=str(expired["invitation_token"]),
        )
