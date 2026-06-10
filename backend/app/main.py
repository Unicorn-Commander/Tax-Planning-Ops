from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.agents import router as agents_router
from app.api.auth import router as auth_router
from app.api.clients import router as clients_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.api.pdf import router as pdf_router
from app.api.plans import router as plans_router
from app.api.quarterly import router as quarterly_router
from app.api.returns import router as returns_router
from app.api.strategies import router as strategies_router
from app.core.auth import JWTAuthMiddleware
from app.core.config import get_settings
from app.db.session import close_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
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
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(clients_router, prefix="/api/v1")
    app.include_router(returns_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(strategies_router, prefix="/api/v1")
    app.include_router(quarterly_router, prefix="/api/v1")
    app.include_router(pdf_router, prefix="/api/v1")
    return app


app = create_app()
