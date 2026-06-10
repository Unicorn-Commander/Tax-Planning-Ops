from __future__ import annotations

from pathlib import Path


def test_single_alembic_head_by_down_revision_graph() -> None:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in versions.glob("*.py"):
        namespace: dict[str, object] = {}
        exec(path.read_text(), namespace)
        revision = namespace["revision"]
        down_revision = namespace["down_revision"]
        assert isinstance(revision, str)
        revisions.add(revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, tuple):
            parents.update(str(item) for item in down_revision)
    assert len(revisions - parents) == 1
