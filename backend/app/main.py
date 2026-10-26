from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.agents import router as agents_router
from app.api.auth import router as auth_router
from app.api.clients import router as clients_router
from app.api.corporate import router as corporate_router
from app.api.demo import router as demo_router
from app.api.engagement import router as engagement_router
from app.api.entities import router as entities_router
from app.api.health import router as health_router
from app.api.intake import router as intake_router
from app.api.journal import router as journal_router
from app.api.lifecycle import router as lifecycle_router
from app.api.matrix import router as matrix_router
from app.api.mcp import router as mcp_router
from app.api.me import router as me_router
from app.api.memo import router as memo_router
from app.api.pats import router as pats_router
from app.api.pdf import router as pdf_router
from app.api.plans import router as plans_router
from app.api.profile import router as profile_router
from app.api.quarterly import router as quarterly_router
from app.api.realized import router as realized_router
from app.api.registry import router as registry_router
from app.api.returns import router as returns_router
from app.api.scenarios import router as scenarios_router
from app.api.strategies import router as strategies_router
from app.api.stream import router as stream_router
from app.api.tasks import router as tasks_router
from app.api.workspaces import router as workspaces_router
from app.core.auth import JWTAuthMiddleware
from app.core.config import get_settings
from app.db.session import close_db
from app.oauth_discovery import MCPPathCORSMiddleware
from app.oauth_discovery import router as oauth_discovery_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    # Don't expose the full API surface (routes/models/examples) unauthenticated
    # in production for a PII-bearing tax product.
    docs_enabled = settings.ENV != "prod"
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Workspace-Id",
            "Mcp-Session-Id",
            "Mcp-Protocol-Version",
            "Last-Event-ID",
        ],
        expose_headers=["Mcp-Session-Id"],
    )
    app.add_middleware(JWTAuthMiddleware, settings=settings)
    # Outermost: MCP preflight and disallowed Origin are answered before auth.
    # Added last so Starlette runs it first.
    app.add_middleware(MCPPathCORSMiddleware)
    # Public OAuth metadata. JWTAuthMiddleware skips this prefix.
    app.include_router(oauth_discovery_router)
    app.include_router(agents_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    # Durable-token self-service (mint/list/revoke tpo_pat_*) + the HTTP MCP
    # door (POST /api/v1/mcp). Both sit behind JWTAuthMiddleware.
    app.include_router(pats_router, prefix="/api/v1")
    app.include_router(mcp_router, prefix="/api/v1")
    app.include_router(lifecycle_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(clients_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(entities_router, prefix="/api/v1")
    # Entity-aware intake: the static "what documents do I need" guidance.
    app.include_router(intake_router, prefix="/api/v1")
    app.include_router(returns_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(strategies_router, prefix="/api/v1")
    app.include_router(quarterly_router, prefix="/api/v1")
    app.include_router(pdf_router, prefix="/api/v1")
    # Phase 9 (additive): memo persistence/sign, scenario+EMR, tasks, realized,
    # the audit-journal read tail. Each resolves to the same engines the GUI and
    # MCP door use.
    app.include_router(memo_router, prefix="/api/v1")
    app.include_router(scenarios_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    app.include_router(realized_router, prefix="/api/v1")
    app.include_router(journal_router, prefix="/api/v1")
    # Wave 2 (the honest-notes backlog): agent registry + door stats, the
    # clients×strategies matrix, firm branding + advisory fee, and the
    # streaming strategist run (Console door 2).
    app.include_router(registry_router, prefix="/api/v1")
    app.include_router(matrix_router, prefix="/api/v1")
    app.include_router(engagement_router, prefix="/api/v1")
    app.include_router(stream_router, prefix="/api/v1")
    # Phase 10: real multi-workspace tenancy (a user's named workspaces + switch)
    # + opt-in demo data (a dedicated 'Sample Firm (demo)' workspace).
    app.include_router(workspaces_router, prefix="/api/v1")
    app.include_router(demo_router, prefix="/api/v1")
    # C-corp / 1120 standalone planning view (federal + state corp tax, AET,
    # double-tax, salary/dividend optimization).
    app.include_router(corporate_router, prefix="/api/v1")
    return app


app = create_app()
