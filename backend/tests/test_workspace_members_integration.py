"""Workspace member/invitation behavior against migrated Postgres RLS.

The normal test run skips this file unless ``TPO_TEST_DATABASE_URL`` points to
the migrated NOBYPASSRLS runtime database, matching test_rls_integration.py.
All subjects and workspace names are fictional and the transaction rolls back.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")
del asyncpg

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
            await transaction.rollback()
    await engine.dispose()


async def _seed_workspace(
    session: AsyncSession,
    workspace_id: str,
    owner_uc_uid: str,
) -> None:
    await bind_session_context(session, workspace_id, owner_uc_uid)
    await session.execute(
        text(
            "INSERT INTO workspaces (id, name) VALUES (:id, :name) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": workspace_id, "name": "Fictional Cedar Tax Group"},
    )
    await session.execute(
        text(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (:id, :uid, :workspace_id, :name, 'owner')"
        ),
        {
            "id": str(uuid4()),
            "uid": owner_uc_uid,
            "workspace_id": workspace_id,
            "name": "Fictional Cedar Tax Group",
        },
    )


@pytest.mark.asyncio
async def test_member_add_invite_accept_roster_and_last_owner_guard(
    db: AsyncSession,
) -> None:
    workspace_id = uuid4()
    owner = "fictional-owner-001"
    direct_member = "fictional-advisor-002"
    invited_member = "fictional-advisor-003"
    second_owner = "fictional-owner-004"
    await _seed_workspace(db, str(workspace_id), owner)

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
    created = await create_invitation(db, workspace_id=workspace_id, actor_uc_uid=owner)
    raw_token = str(created["invitation_token"])
    invitation_row = (
        await db.execute(
            text(
                "SELECT token_hash FROM workspace_invitation "
                "WHERE token_hash = :token_hash"
            ),
            {"token_hash": hash_invitation_token(raw_token)},
        )
    ).first()
    assert invitation_row is not None
    assert invitation_row.token_hash == hash_invitation_token(raw_token)

    accepted = await accept_invitation(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=invited_member,
        raw_token=raw_token,
    )
    assert accepted.user_uc_uid == invited_member
    assert accepted.role == "member"
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

    # Seed a second owner through the owner-authorized RLS path, remove it, then
    # prove the remaining owner cannot be removed as the last owner.
    await bind_session_context(db, str(workspace_id), owner)
    await db.execute(
        text(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (:id, :uid, :workspace_id, :name, 'owner')"
        ),
        {
            "id": str(uuid4()),
            "uid": second_owner,
            "workspace_id": str(workspace_id),
            "name": "Fictional Cedar Tax Group",
        },
    )
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

    await bind_session_context(db, str(workspace_id), owner)
    expired = await create_invitation(db, workspace_id=workspace_id, actor_uc_uid=owner)
    await db.execute(
        text(
            "UPDATE workspace_invitation SET expires_at = now() - interval '1 minute' "
            "WHERE token_hash = :token_hash"
        ),
        {"token_hash": hash_invitation_token(str(expired["invitation_token"]))},
    )
    with pytest.raises(InvalidInvitationError):
        await accept_invitation(
            db,
            workspace_id=workspace_id,
            actor_uc_uid="fictional-advisor-007",
            raw_token=str(expired["invitation_token"]),
        )
