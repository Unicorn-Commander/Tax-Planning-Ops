"""Deploy config carries the entitlement door's two settings, values unset.

The ring values (dogfood / production Ops-Center origins) are set at release
in the ring's .env, never defaulted in compose or code.
"""

from __future__ import annotations

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_compose_passes_both_settings_without_a_ring_default() -> None:
    compose = (DEPLOY / "docker-compose.yml").read_text()
    assert re.search(
        r"^\s+ENTITLEMENT_CHECK_ENABLED: \$\{ENTITLEMENT_CHECK_ENABLED:-false\}$",
        compose,
        re.M,
    )
    # No default: an unset ring must not silently point at another ring.
    assert re.search(r"^\s+OPS_CENTER_URL: \$\{OPS_CENTER_URL:-\}$", compose, re.M)


def test_env_example_documents_both_settings_per_ring() -> None:
    example = (DEPLOY / ".env.example").read_text()
    assert re.search(r"^ENTITLEMENT_CHECK_ENABLED=false$", example, re.M)
    assert re.search(r"^OPS_CENTER_URL=$", example, re.M)
    assert "https://magicunicorn.dev" in example
    assert "https://unicorncommander.ai" in example
    # The ring URLs appear only in comments, never as a live value.
    for line in example.splitlines():
        if "magicunicorn.dev" in line and "OPS_CENTER" in line:
            assert line.lstrip().startswith("#"), line
