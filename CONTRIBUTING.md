# Contributing

Tax-Planning-Ops plans. It does not prepare or file a return. Keep new screens and agent copy on the same side of that line: a figure on screen comes from the engine, and the plan disclaimer stays attached to anything a client might read.

## Prerequisites

- Python 3.12
- Node.js 22
- Postgres 17

The laptop setup is in the [README](README.md#quick-start). `STANDALONE_MODE=true` with `ENV=dev` skips Keycloak. It will not boot when `ENV=prod`.

## Checks

These are the commands CI runs (`.github/workflows/ci.yml`).

Backend, from `backend/`:

```bash
pip install -r requirements-dev.txt
ruff check app tests scripts
mypy app
pytest
```

The row-level-security test is marked `integration` and skips unless `TPO_TEST_DATABASE_URL` points at a migrated database as `tax_planning_ops_app`. CI migrates first (`python -m app.db.bootstrap`), then runs `pytest -m integration`. It also fails the job unless `backend/alembic/versions/` has a single head.

Frontend, from `frontend/`:

```bash
npm ci
npm run lint
npm run build
```

MCP, from the repository root. These tests stub HTTP and are not on the backend pytest path (`testpaths` is `backend/tests`):

```bash
pytest mcp/test_server.py
```

`python mcp/test_server.py` runs the same file. The server imports the `mcp` package, which is not listed in `backend/requirements.in`.

## Pull requests

- One concern per change. Say which engine, route, or screen you touched.
- Do not commit `.env` files, tokens, or a real tax return. The demo seed in `backend/app/services/demo_seed.py` is the fixture to extend.
- New tax math belongs in `backend/app/engines/` as a pure function with a test, then a route that calls it. The MCP server should gain a line in `mcp/tools.json` and the tool name in `mcp/manifest.json`, not a second implementation.
- Product copy that a client could read keeps the planning disclaimer.

## Licence

This repository is [AGPL-3.0-or-later](LICENSE). Contributions are under that same licence.
