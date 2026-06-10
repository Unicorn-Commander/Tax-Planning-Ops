#!/bin/sh
set -e

echo "[entrypoint] bootstrap: role password sync + alembic upgrade head"
python -m app.db.bootstrap

echo "[entrypoint] starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
