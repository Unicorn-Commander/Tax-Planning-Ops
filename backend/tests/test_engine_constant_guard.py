from __future__ import annotations

from pathlib import Path


def test_no_high_liability_irs_constants_in_engines() -> None:
    engine_root = Path(__file__).resolve().parents[1] / "app" / "engines"
    forbidden = ["0.37", "0.038", "0.009", "14600", "29200", "3000"]
    offenders: list[str] = []
    for path in engine_root.glob("*.py"):
        text = path.read_text()
        for literal in forbidden:
            if literal in text:
                offenders.append(f"{path.name}:{literal}")
    assert offenders == []
