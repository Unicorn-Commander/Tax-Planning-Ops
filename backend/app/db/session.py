from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.core.config import Settings, get_settings
from app.schemas.auth import AuthContext

_settings = get_settings()


def _json_serializer(value: object) -> str:
    # UUID/datetime/Decimal appear in JSONB payloads (audit, assumptions,
    # extraction_raw); str-default here matches compute_audit_hash's
    # canonicalization so stored payloads re-hash identically on verify.
    return json.dumps(value, default=str)


def _make_engine(dsn: str):  # type: ignore[no-untyped-def]
    return create_async_engine(
        dsn,
        poolclass=AsyncAdaptedQueuePool,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        json_serializer=_json_serializer,
    )


engine = _make_engine(_settings.DATABASE_URL)
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def bind_session_context(
    session: AsyncSession,
    workspace_id: str,
    uc_uid: str | None,
    settings: Settings | None = None,
) -> None:
    cfg = settings or _settings
    await session.execute(
        text("SELECT set_config(:k, :v, true)"),
        {"k": cfg.WORKSPACE_GUC_NAME, "v": str(workspace_id)},
    )
    await session.execute(
        text("SELECT set_config(:k, :v, true)"),
        {"k": cfg.UC_UID_GUC_NAME, "v": str(uc_uid or "")},
    )


# Workspaces provisioned this process (skip the upsert after first sight).
_provisioned: set[str] = set()


async def ensure_workspace(session: AsyncSession, workspace_id: str, name: str | None) -> None:
    """Mirror the control-plane workspace row on first authenticated use.

    The id comes from the verified JWT claim, and the RLS WITH CHECK on
    `workspaces` guarantees a token can only create its OWN row. Idempotent;
    cached per process. This is what lets a brand-new firm transact without an
    out-of-band provisioning step.
    """
    if workspace_id in _provisioned:
        return
    await session.execute(
        text(
            "INSERT INTO workspaces (id, name) VALUES (:id, :name) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": workspace_id, "name": name or f"Workspace {workspace_id[:8]}"},
    )
    _provisioned.add(workspace_id)


def get_auth_context(request: Request) -> AuthContext:
    ctx = getattr(request.state, "auth_context", None)
    if not isinstance(ctx, AuthContext):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication context unresolved",
        )
    return ctx


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_tenant_db(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[AsyncSession, None]:
    ctx = get_auth_context(request)
    async with async_session_maker() as session:
        await bind_session_context(session, str(ctx.workspace_id), ctx.uc_uid, settings)
        workspace_name = ctx.claims.get("workspace_name") or ctx.claims.get("tenant_name")
        await ensure_workspace(session, str(ctx.workspace_id), workspace_name)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    await engine.dispose()
