"""2025 state income tax configs (registry).

Lives outside app/engines/ (constants belong here, not in the engine). Covers
the 9 no-income-tax states + the flat-rate states; the bracketed states (CA, NY,
NJ, VA, OH) are added from their bracket tables. Constants research- and
adversarially-verified against the official 2025 state sources (FTB, NY DTF,
mass.gov, tax.illinois.gov, pa.gov, NCDOR, AZDOR, Virginia Tax, NJ Div of Tax).

`get_state_config(state, tax_year)` returns a StateTaxConfig or None (unknown /
not-yet-modeled state). Year-aware where a state's rate changed (e.g. NC).
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.state_tax import StateSurtax, StateTaxConfig

NO_INCOME_TAX = ["TX", "FL", "WA", "NV", "SD", "WY", "AK", "TN", "NH"]


def _flat(
    state: str, rate: str, *, std_single: int, std_mfj: int,
    taxes_ss: bool, taxes_retirement: bool, surtaxes: list[StateSurtax] | None = None,
) -> StateTaxConfig:
    return StateTaxConfig(
        state=state, flat_rate=Decimal(rate),
        standard_deduction_by_status={"single": std_single, "mfj": std_mfj},
        taxes_social_security=taxes_ss, taxes_retirement_income=taxes_retirement,
        surtaxes=surtaxes or [], starts_from="federal_agi",
    )


def get_state_config(state: str, tax_year: int = 2025) -> StateTaxConfig | None:
    s = (state or "").upper()
    if s in NO_INCOME_TAX:
        return StateTaxConfig(state=s, has_income_tax=False)

    if s == "IL":  # flat 4.95%; personal exemption $2,850/$5,700; retirement + SS exempt
        return _flat("IL", "0.0495", std_single=285_000, std_mfj=570_000,
                     taxes_ss=False, taxes_retirement=False)
    if s == "PA":  # flat 3.07%; no deduction; SS + qualified retirement exempt
        return _flat("PA", "0.0307", std_single=0, std_mfj=0,
                     taxes_ss=False, taxes_retirement=False)
    if s == "MA":  # flat 5% + 4% millionaire surtax over $1,083,150 (all statuses); SS exempt
        return _flat("MA", "0.05", std_single=440_000, std_mfj=880_000,
                     taxes_ss=False, taxes_retirement=True,
                     surtaxes=[StateSurtax(
                         name="Fair Share surtax", threshold_cents=108_315_000,
                         rate=Decimal("0.04"), applies_to="state_taxable_income")])
    if s == "GA":  # flat 5.39% (2024) → 5.19% (2025 HB111 retroactive); std $12k/$24k; SS exempt
        rate = "0.0519" if tax_year >= 2025 else "0.0539"
        return _flat("GA", rate, std_single=1_200_000, std_mfj=2_400_000,
                     taxes_ss=False, taxes_retirement=True)
    if s == "NC":  # flat 4.25% (2025) → 3.99% (2026); std $12,750/$25,500; SS exempt
        rate = "0.0399" if tax_year >= 2026 else "0.0425"
        return _flat("NC", rate, std_single=1_275_000, std_mfj=2_550_000,
                     taxes_ss=False, taxes_retirement=True)
    if s == "AZ":  # flat 2.5%; std matches federal $15,750/$31,500; SS exempt
        return _flat("AZ", "0.025", std_single=1_575_000, std_mfj=3_150_000,
                     taxes_ss=False, taxes_retirement=True)

    # CA / NY / NJ / VA / OH — bracketed, added from BRACKETED_STATES below.
    return _BRACKETED.get(s)


# Bracketed-state configs are registered here once their exact 2025 bracket
# tables are encoded (see app/state_brackets.py).
_BRACKETED: dict[str, StateTaxConfig] = {}


def register_bracketed(configs: dict[str, StateTaxConfig]) -> None:
    _BRACKETED.update(configs)


# Import for its registration side effect (defined after register_bracketed to
# avoid a circular import).
from app import state_brackets  # noqa: E402,F401
