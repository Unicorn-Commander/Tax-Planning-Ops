"""Client planning-profile CRUD (1:1 with a client).

The profile is the client's *objectives* — the goals the strategist reads to
make its advice situation-aware. Upsert semantics: one row per client, created
on first save and updated thereafter."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import ClientPlanningProfile
from app.schemas.profile import PlanningProfileIn
from app.services.audit import append_audit_event


async def get_profile(
    db: AsyncSession, *, client_id: UUID
) -> ClientPlanningProfile | None:
    profile: ClientPlanningProfile | None = await db.scalar(
        select(ClientPlanningProfile).where(ClientPlanningProfile.client_id == client_id)
    )
    return profile


async def upsert_profile(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    client_id: UUID,
    payload: PlanningProfileIn,
) -> ClientPlanningProfile:
    profile = await get_profile(db, client_id=client_id)
    if profile is None:
        profile = ClientPlanningProfile(
            workspace_id=workspace_id, client_id=client_id, **payload.model_dump()
        )
        db.add(profile)
        event_type = "planning_profile_created"
    else:
        for field, value in payload.model_dump().items():
            setattr(profile, field, value)
        event_type = "planning_profile_updated"
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type=event_type,
        aggregate_type="client_planning_profile",
        aggregate_id=profile.id,
        payload=payload.model_dump(mode="json"),
    )
    return profile
