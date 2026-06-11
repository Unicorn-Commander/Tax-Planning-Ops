"""Bracketed-state 2025 configs (CA, NY, NJ, VA), registered into the state
registry. Bracket tables fetched from the official 2025 sources (FTB Schedule
X/Y, NY IT-201-I, NJ-1040 schedules, Virginia Tax) and verified to reproduce the
adversarially-checked golden vectors.

NY note: NY imposes a mandatory tax-benefit recapture above ~$107,650 NYAGI that
this base-bracket model does NOT apply, so NY tax is UNDERSTATED for high earners
(flagged at runtime). OH is not here — it uses statutory base amounts the
bracket engine can't yet represent.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.form1040 import RateBracket
from app.engines.state_tax import StateSurtax, StateTaxConfig
from app.state_configs import register_bracketed


def _brk(rows: list[tuple[int, int | None, str]]) -> list[RateBracket]:
    return [
        RateBracket(
            lower_bound_cents=lo * 100,
            upper_bound_cents=(None if up is None else up * 100),
            rate=Decimal(rate),
        )
        for lo, up, rate in rows
    ]


CA = StateTaxConfig(
    state="CA",
    brackets_by_status={
        "single": _brk([
            (0, 11079, "0.01"), (11079, 26264, "0.02"), (26264, 41452, "0.04"),
            (41452, 57542, "0.06"), (57542, 72724, "0.08"), (72724, 371479, "0.093"),
            (371479, 445771, "0.103"), (445771, 742953, "0.113"), (742953, None, "0.123"),
        ]),
        "mfj": _brk([
            (0, 22158, "0.01"), (22158, 52528, "0.02"), (52528, 82904, "0.04"),
            (82904, 115084, "0.06"), (115084, 145448, "0.08"), (145448, 742958, "0.093"),
            (742958, 891542, "0.103"), (891542, 1485906, "0.113"), (1485906, None, "0.123"),
        ]),
    },
    standard_deduction_by_status={"single": 570_600, "mfj": 1_141_200},
    taxes_social_security=False, taxes_retirement_income=True,
    surtaxes=[StateSurtax(name="Mental Health Services", threshold_cents=100_000_000,
                          rate=Decimal("0.01"), applies_to="state_taxable_income")],
)

NY = StateTaxConfig(
    state="NY",
    brackets_by_status={
        "single": _brk([
            (0, 8500, "0.04"), (8500, 11700, "0.045"), (11700, 13900, "0.0525"),
            (13900, 80650, "0.055"), (80650, 215400, "0.06"), (215400, 1077550, "0.0685"),
            (1077550, 5000000, "0.0965"), (5000000, 25000000, "0.103"), (25000000, None, "0.109"),
        ]),
        "mfj": _brk([
            (0, 17150, "0.04"), (17150, 23600, "0.045"), (23600, 27900, "0.0525"),
            (27900, 161550, "0.055"), (161550, 323200, "0.06"), (323200, 2155350, "0.0685"),
            (2155350, 5000000, "0.0965"), (5000000, 25000000, "0.103"), (25000000, None, "0.109"),
        ]),
    },
    standard_deduction_by_status={"single": 800_000, "mfj": 1_605_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

NJ = StateTaxConfig(
    state="NJ",
    brackets_by_status={
        "single": _brk([
            (0, 20000, "0.014"), (20000, 35000, "0.0175"), (35000, 40000, "0.035"),
            (40000, 75000, "0.05525"), (75000, 500000, "0.0637"), (500000, 1000000, "0.0897"),
            (1000000, None, "0.1075"),
        ]),
        "mfj": _brk([
            (0, 20000, "0.014"), (20000, 50000, "0.0175"), (50000, 70000, "0.0245"),
            (70000, 80000, "0.035"), (80000, 150000, "0.05525"), (150000, 500000, "0.0637"),
            (500000, 1000000, "0.0897"), (1000000, None, "0.1075"),
        ]),
    },
    standard_deduction_by_status={"single": 0, "mfj": 0},
    taxes_social_security=False, taxes_retirement_income=True,
)

_VA_BRACKETS = _brk([(0, 3000, "0.02"), (3000, 5000, "0.03"), (5000, 17000, "0.05"),
                     (17000, None, "0.0575")])
VA = StateTaxConfig(
    state="VA",
    brackets_by_status={"single": _VA_BRACKETS, "mfj": _VA_BRACKETS},
    standard_deduction_by_status={"single": 875_000, "mfj": 1_750_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

register_bracketed({"CA": CA, "NY": NY, "NJ": NJ, "VA": VA})
