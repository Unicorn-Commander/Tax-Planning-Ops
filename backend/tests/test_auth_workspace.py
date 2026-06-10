from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.auth import resolve_workspace_id


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
