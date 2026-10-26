"""Fail unless alembic/versions has exactly one head (CI guard against forked migration history)."""
import sys
from pathlib import Path


def count_heads(versions: Path) -> int:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in versions.glob("*.py"):
        ns: dict = {}
        exec(path.read_text(), ns)
        revisions.add(ns["revision"])
        down = ns["down_revision"]
        if isinstance(down, str):
            parents.add(down)
        elif isinstance(down, tuple):
            parents.update(down)
    return len(revisions - parents)


if __name__ == "__main__":
    heads = count_heads(Path("alembic/versions"))
    print(f"alembic heads: {heads}")
    sys.exit(0 if heads == 1 else 1)
