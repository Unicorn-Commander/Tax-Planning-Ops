from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def list_tools() -> list[dict[str, Any]]:
    return json.loads((Path(__file__).with_name("tools.json")).read_text())


if __name__ == "__main__":
    print(json.dumps({"tools": list_tools()}, indent=2))
