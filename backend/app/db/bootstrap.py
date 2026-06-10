"""Deploy-time bootstrap: role password sync + Alembic migrations.

Runs as the migration role (MIGRATION_DATABASE_URL) before the API starts:

1. Ensure the NOBYPASSRLS runtime role exists and its password matches
   RUNTIME_DB_PASSWORD (the migration that creates the role cannot carry a
   secret, so the password is synced here from the environment).
2. Run ``alembic upgrade head``.

Invoked by the container entrypoint: ``python -m app.db.bootstrap``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

logger = logging.getLogger("tax_planning_ops.bootstrap")

APP_ROLE = "tax_planning_ops_app"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migration_url() -> str:
    url = (
        os.environ.get("MIGRATION_DATABASE_URL")
        or os.environ.get("ALEMBIC_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise RuntimeError("Set MIGRATION_DATABASE_URL (or DATABASE_URL) for bootstrap")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


async def _ensure_app_role(url: str) -> None:
    password = os.environ.get("RUNTIME_DB_PASSWORD", "")
    engine = create_async_engine(url, poolclass=None)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT FROM pg_catalog.pg_roles WHERE rolname = '{APP_ROLE}'
                        ) THEN
                            CREATE ROLE {APP_ROLE}
                            LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
                        END IF;
                    END $$
                    """
                )
            )
            if password:
                quoted = password.replace("'", "''")
                alter = (
                    f"ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOBYPASSRLS "
                    f"PASSWORD '{quoted}'"
                )
                await conn.execute(text(alter))
                logger.info("synced %s password from RUNTIME_DB_PASSWORD", APP_ROLE)
            else:
                logger.warning(
                    "RUNTIME_DB_PASSWORD not set; %s password left unchanged", APP_ROLE
                )
    finally:
        await engine.dispose()


def _run_migrations() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    url = _migration_url()
    asyncio.run(_ensure_app_role(url))
    logger.info("running alembic upgrade head")
    _run_migrations()
    logger.info("bootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
