"""Workspace-org backfill (task 33982835, round 2): validate and apply an
OPERATOR-SUPPLIED mapping file (workspace_id -> org_id), guarded and idempotent.

Workspaces created before the entitlement door (PR #15, alembic 0023) have
``workspaces.org_id`` NULL and are refused once ``ENTITLEMENT_CHECK_ENABLED``
is on. Ops-Center serves no endpoint that answers, with an operator
credential, whether some OTHER user's org exists, holds ``tax_ops_access``
or has that user as a member — its org routes answer only for the caller's
own session (the door in ``app/integrations/control_plane.py`` is the only
existing call, and it speaks for its own bearer). So this backfill does NOT
ask Ops-Center anything: it validates and applies a mapping file produced
by the Ops-Center owner.

Live checks (what Tax owns): the workspace exists, its ``org_id`` is NULL,
it has an owner-role member (``workspace_membership``, ``role = 'owner'``,
not deleted), the mapped ``org_id`` is a canonical UUID, and no workspace
is listed twice. Anything invalid is refused, left NULL and listed with a
reason. The Ops-Center side (org exists, holds ``tax_ops_access``, the owner
is a member) is TRUSTED from the mapping file — see ``TRUSTED_NOTE``, which
the CLI prints with every run.

Each bind is its own guarded transaction: ``UPDATE workspaces SET org_id =
:org WHERE id = :ws AND org_id IS NULL`` — exactly one row or rollback; a
non-NULL org_id is never overwritten (the 0023 trigger forbids changing a
bound org too). A re-run finds every mapped workspace already bound: a
no-op. ``dry_run`` validates and reports but writes nothing. Output is
workspace ids and fixed reasons only — never emails or owner names.

Runs as the OWNER database role (the app role's RLS cannot see other
workspaces); the CLI lives in scripts/backfill_workspace_org.py. No
migration, no data change here — this module only implements the guarded
procedure.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Printed with every run: which checks are live and which are trusted.
TRUSTED_NOTE = (
    "Ops-Center side (org exists, holds tax_ops_access, the owner is a "
    "member) is TRUSTED from the mapping file: Ops-Center serves no "
    "endpoint that answers for other users' orgs with an operator "
    "credential."
)


class MappingFileError(Exception):
    """The mapping file cannot be read or parsed at all (not a row problem)."""


@dataclass(frozen=True)
class MappingRow:
    """One mapping-file entry: bind ``workspace_id`` to ``org_id`` (raw
    string; the canonical-UUID check is a service-side validation). ``ref``
    locates the entry in the file (e.g. "line 3", "entry 2", "key <id>")."""

    workspace_id: UUID
    org_id: str
    ref: str


@dataclass(frozen=True)
class Refusal:
    """A refused row: ``ref`` is the workspace id when the id parsed, else
    the file location; ``reason`` is one of the fixed strings below."""

    ref: str
    reason: str


@dataclass
class BackfillResult:
    """Outcomes of one run. ``bound`` lists workspace ids only; ``refused``
    lists (id-or-location, fixed reason) — never emails or owner names."""

    bound: list[UUID] = field(default_factory=list)
    refused: list[Refusal] = field(default_factory=list)


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        canonical = str(UUID(value))
    except ValueError:
        return None
    return canonical if canonical == value else None


def _rows_from_items(
    items: Sequence[tuple[str, object, object]],
    refused: list[Refusal],
) -> list[MappingRow]:
    rows: list[MappingRow] = []
    for ref, ws_raw, org_raw in items:
        ws = _canonical_uuid(ws_raw)
        if ws is None:
            refused.append(Refusal(ref, "workspace_id is not a uuid"))
            continue
        if not isinstance(org_raw, str):
            refused.append(Refusal(ref, "org_id is not a string"))
            continue
        rows.append(MappingRow(workspace_id=UUID(ws), org_id=org_raw, ref=ref))
    return rows


def _load_csv(raw: str) -> tuple[list[MappingRow], list[Refusal]]:
    reader = csv.DictReader(raw.splitlines())
    if not reader.fieldnames or not {"workspace_id", "org_id"} <= set(reader.fieldnames):
        raise MappingFileError("CSV needs a header with workspace_id and org_id columns")
    refused: list[Refusal] = []
    items: list[tuple[str, object, object]] = []
    for n, entry in enumerate(reader, start=2):  # header is line 1
        items.append((f"line {n}", (entry.get("workspace_id") or "").strip(),
                      (entry.get("org_id") or "").strip()))
    return _rows_from_items(items, refused), refused


def _load_json(raw: str) -> tuple[list[MappingRow], list[Refusal]]:
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise MappingFileError(f"not valid JSON: {exc}") from exc
    refused: list[Refusal] = []
    items: list[tuple[str, object, object]] = []
    if isinstance(body, dict):
        items = [(f"key {key}", key, value) for key, value in body.items()]
    elif isinstance(body, list):
        for n, entry in enumerate(body, start=1):
            ref = f"entry {n}"
            if not isinstance(entry, dict) or not {
                "workspace_id",
                "org_id",
            } <= set(entry):
                refused.append(Refusal(ref, "entry is not a workspace_id/org_id object"))
                continue
            items.append((ref, entry["workspace_id"], entry["org_id"]))
    else:
        raise MappingFileError("JSON must be an object or a list of objects")
    return _rows_from_items(items, refused), refused


def load_mapping(path: Path) -> tuple[list[MappingRow], list[Refusal]]:
    """Parse a mapping file (CSV with a ``workspace_id,org_id`` header, or
    JSON: an object mapping workspace_id to org_id, or a list of
    {"workspace_id", "org_id"} objects). Rows whose workspace_id is not a
    canonical UUID are refused with their file location; a file that cannot
    be parsed at all raises MappingFileError."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MappingFileError(f"cannot read {path.name}: {exc.strerror or exc}") from exc
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(raw)
    if suffix == ".csv":
        return _load_csv(raw)
    try:
        return _load_json(raw)
    except MappingFileError:
        return _load_csv(raw)


# One round trip per workspace: bound yet? owner yet?
_CHECK_WS = text(
    "SELECT w.org_id IS NULL AS unbound, "
    "EXISTS (SELECT 1 FROM workspace_membership m "
    "WHERE m.workspace_id = w.id AND m.role = 'owner' AND m.deleted_at IS NULL"
    ") AS has_owner "
    "FROM workspaces w WHERE w.id = :ws"
)

# Guarded bind: the WHERE repeats the NULL precondition, so a row bound by
# someone else in between matches zero rows and rolls the transaction back.
_BIND = text("UPDATE workspaces SET org_id = :org WHERE id = :ws AND org_id IS NULL")


async def backfill_workspace_orgs(
    session_factory: async_sessionmaker[AsyncSession],
    rows: Sequence[MappingRow],
    *,
    dry_run: bool = False,
) -> BackfillResult:
    """Validate each mapping row against what Tax owns and bind the valid
    ones (``dry_run``: validate and report, write nothing).

    ``session_factory`` must be bound to the OWNER role (RLS bypass). One
    guarded transaction per workspace; never overwrites a bound org;
    idempotent: a re-run refuses every already-bound workspace and writes
    nothing. The Ops-Center side is trusted from the mapping file."""
    result = BackfillResult()
    counts: dict[UUID, int] = {}
    for row in rows:
        counts[row.workspace_id] = counts.get(row.workspace_id, 0) + 1

    for row in rows:
        ws = row.workspace_id
        ref = str(ws)
        if counts[ws] > 1:
            # Whose line wins? Nobody's: refuse every listing of it.
            result.refused.append(
                Refusal(ref, "workspace listed more than once in the mapping")
            )
            continue
        if _canonical_uuid(row.org_id) is None:
            result.refused.append(Refusal(ref, "org_id is not a canonical uuid"))
            continue
        async with session_factory() as session:
            check = (await session.execute(_CHECK_WS, {"ws": ref})).first()
        if check is None:
            result.refused.append(Refusal(ref, "workspace not found"))
            continue
        if not check.unbound:
            result.refused.append(Refusal(ref, "workspace already bound"))
            continue
        if not check.has_owner:
            result.refused.append(Refusal(ref, "no owner member"))
            continue
        if dry_run:
            result.bound.append(ws)
            continue
        async with session_factory() as session:
            outcome = cast(
                CursorResult[Any],
                await session.execute(_BIND, {"org": row.org_id, "ws": ref}),
            )
            if outcome.rowcount == 1:
                await session.commit()
                result.bound.append(ws)
            else:
                # Someone bound it in between (or it vanished): roll back.
                await session.rollback()
                result.refused.append(Refusal(ref, "bind raced: org_id no longer NULL"))
    return result
