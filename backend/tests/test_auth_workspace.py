from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.auth import derive_self_serve_workspace, resolve_workspace_id


def test_header_can_select_authorized_workspace() -> None:
    workspace_a = UUID("00000000-0000-0000-0000-00000000000a")
    workspace_b = UUID("00000000-0000-0000-0000-00000000000b")
    selected, authorized = resolve_workspace_id(
        {
            "sub": "user-1",
            "workspace_id": str(workspace_a),
            "workspaces": [{"workspaceId": str(workspace_b)}],
        },
        str(workspace_b),
    )
    assert selected == workspace_b
    assert authorized == {workspace_a, workspace_b}


def test_forged_workspace_header_is_denied() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(
            {
                "sub": "user-1",
                "workspace_id": "00000000-0000-0000-0000-00000000000a",
            },
            "00000000-0000-0000-0000-00000000000b",
        )
    assert exc.value.status_code == 403


def test_self_serve_derives_own_workspace_from_sub() -> None:
    # No explicit workspace claim -> a deterministic, isolated own workspace.
    selected, authorized = resolve_workspace_id({"sub": "uc-user-xyz"}, None)
    assert authorized == {selected}
    # deterministic for the same subject
    again, _ = resolve_workspace_id({"sub": "uc-user-xyz"}, None)
    assert again == selected
    # distinct subjects -> distinct (isolated) workspaces
    other, _ = resolve_workspace_id({"sub": "uc-user-abc"}, None)
    assert other != selected


def test_self_serve_helper_returns_none_when_workspace_claim_present() -> None:
    # An explicit workspace claim is NOT self-serve (managed workspace path).
    assert (
        derive_self_serve_workspace(
            {"sub": "u", "workspace_id": "00000000-0000-0000-0000-00000000000a"}
        )
        is None
    )


def test_self_serve_forged_header_still_denied() -> None:
    # A self-serve user cannot select someone else's workspace via the header.
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id({"sub": "uc-user-xyz"}, "00000000-0000-0000-0000-00000000000b")
    assert exc.value.status_code == 403


def test_no_subject_no_workspace_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id({}, None)
    assert exc.value.status_code == 401
