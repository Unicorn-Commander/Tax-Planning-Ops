from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.agents import router as agents_router
from app.api.auth import router as auth_router
from app.api.clients import router as clients_router
from app.api.entities import router as entities_router
from app.api.health import router as health_router
from app.api.journal import router as journal_router
from app.api.lifecycle import router as lifecycle_router
from app.api.me import router as me_router
from app.api.memo import router as memo_router
from app.api.pdf import router as pdf_router
from app.api.plans import router as plans_router
from app.api.profile import router as profile_router
from app.api.quarterly import router as quarterly_router
from app.api.realized import router as realized_router
from app.api.returns import router as returns_router
from app.api.scenarios import router as scenarios_router
from app.api.strategies import router as strategies_router
from app.api.tasks import router as tasks_router
from app.core.auth import JWTAuthMiddleware
from app.core.config import get_settings
from app.db.session import close_db


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
        allow_headers=["Authorization", "Content-Type", "X-Workspace-Id"],
    )
    app.add_middleware(JWTAuthMiddleware, settings=settings)
    app.include_router(agents_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(lifecycle_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(clients_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(entities_router, prefix="/api/v1")
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
    return app


app = create_app()
