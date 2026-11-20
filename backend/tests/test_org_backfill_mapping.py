"""Mapping-file loading for the workspace-org backfill (task 33982835, round 2).

The backfill takes an OPERATOR-SUPPLIED mapping file (workspace_id -> org_id,
produced by the Ops-Center owner) as CSV (header ``workspace_id,org_id``) or
JSON (an object mapping workspace_id to org_id, or a list of
{"workspace_id", "org_id"} objects). ``load_mapping`` parses it into
MappingRows and refuses rows whose workspace_id is not a UUID; a file it
cannot parse at all raises MappingFileError. org_id is kept as the raw
string: the canonical-UUID check is a service-side validation (see the
integration file). No DB, no network; all ids are fictional.

Red on 275749d: app.services.org_backfill has no load_mapping/MappingRow/
MappingFileError (ImportError).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.services.org_backfill import MappingFileError, MappingRow, load_mapping

ORG_A = "11111111-2222-4333-8444-555555555555"
ORG_B = "22222222-3333-4444-8555-666666666666"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_csv_happy_path(tmp_path: Path) -> None:
    ws1, ws2 = str(uuid4()), str(uuid4())
    path = _write(
        tmp_path,
        "map.csv",
        f"workspace_id,org_id\n{ws1},{ORG_A}\n{ws2},{ORG_B}\n",
    )
    rows, refused = load_mapping(path)
    assert refused == []
    assert [(r.workspace_id, r.org_id) for r in rows] == [
        (UUID(ws1), ORG_A),
        (UUID(ws2), ORG_B),
    ]


def test_csv_extra_columns_and_order_ignored(tmp_path: Path) -> None:
    ws = str(uuid4())
    path = _write(
        tmp_path,
        "map.csv",
        f"note,org_id,workspace_id\nanything,{ORG_A},{ws}\n",
    )
    rows, refused = load_mapping(path)
    assert refused == []
    assert [(r.workspace_id, r.org_id) for r in rows] == [(UUID(ws), ORG_A)]


def test_json_object_happy_path(tmp_path: Path) -> None:
    ws = str(uuid4())
    path = _write(tmp_path, "map.json", f'{{"{ws}": "{ORG_A}"}}')
    rows, refused = load_mapping(path)
    assert refused == []
    assert [(r.workspace_id, r.org_id) for r in rows] == [(UUID(ws), ORG_A)]


def test_json_list_happy_path(tmp_path: Path) -> None:
    ws = str(uuid4())
    path = _write(
        tmp_path,
        "map.json",
        f'[{{"workspace_id": "{ws}", "org_id": "{ORG_A}"}}]',
    )
    rows, refused = load_mapping(path)
    assert refused == []
    assert [(r.workspace_id, r.org_id) for r in rows] == [(UUID(ws), ORG_A)]


def test_non_uuid_workspace_id_refused_with_line(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "map.csv",
        f"workspace_id,org_id\nnot-a-uuid,{ORG_A}\n{str(uuid4())},{ORG_B}\n",
    )
    rows, refused = load_mapping(path)
    assert len(rows) == 1
    assert len(refused) == 1
    assert refused[0].ref == "line 2"
    assert refused[0].reason == "workspace_id is not a uuid"


def test_non_string_json_values_refused(tmp_path: Path) -> None:
    ws = str(uuid4())
    path = _write(tmp_path, "map.json", f'{{"{ws}": 7}}')
    rows, refused = load_mapping(path)
    assert rows == []
    assert refused[0].reason == "org_id is not a string"


def test_csv_without_required_header_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "map.csv", "ws,org\nx,y\n")
    with pytest.raises(MappingFileError):
        load_mapping(path)


def test_malformed_json_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "map.json", "{not json")
    with pytest.raises(MappingFileError):
        load_mapping(path)


def test_json_list_entry_missing_keys_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "map.json", '[{"workspace_id": "x"}]')
    rows, refused = load_mapping(path)
    assert rows == []
    assert refused[0].reason == "entry is not a workspace_id/org_id object"


def test_rows_carry_ref_for_error_reporting(tmp_path: Path) -> None:
    ws = str(uuid4())
    path = _write(tmp_path, "map.csv", f"workspace_id,org_id\n{ws},{ORG_A}\n")
    rows, _ = load_mapping(path)
    assert isinstance(rows[0], MappingRow)
    assert rows[0].ref == "line 2"
