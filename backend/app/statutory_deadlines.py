"""Static, code-side catalog of common federal statutory planning deadlines.

This is reference data, not an engine: a small frozen table of the deadlines a
planning task can hang off of, each with a citation and a resolver that turns a
``tax_year`` into the actual calendar date. The ``ImplementationTask`` model
stores only the ``statutory_key``; the UI resolves the label/citation/date from
here so the contract row can show "by Apr 15, 2027 (IRC §6654)".

Dates use the conventional statutory dates. We deliberately do NOT shift for
weekends/holidays (the IRS Emancipation-Day/weekend roll) — the planning chase
wants the canonical date, and the few days of slack are immaterial to a deadline
the advisor is steering toward weeks ahead. Each entry documents its rule inline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

# A resolver maps a tax year to its deadline date: (tax_year:int) -> date.
DeadlineResolver = Callable[[int], date]


@dataclass(frozen=True)
class StatutoryDeadline:
    """One catalog entry: a stable ``key``, a human ``label``, the governing
    ``citation`` (IRC section or IRS form), and a ``resolver`` that maps a tax
    year to its calendar date. ``resolver`` takes the tax year (the year the
    income/return is FOR) and returns the deadline ``date``."""

    key: str
    label: str
    citation: str
    resolver: DeadlineResolver


# --------------------------------------------------------------------------- #
# Resolvers. ``tax_year`` is the year the income is earned / the return is for.
# The filing/payment deadline for a calendar-year taxpayer generally falls in
# the FOLLOWING year (tax_year + 1); in-year quarterly estimates fall within the
# tax year itself.
# --------------------------------------------------------------------------- #
def _apr15_next(tax_year: int) -> date:
    """Apr 15 of the year AFTER the tax year — the unextended 1040 due date and
    the last day for prior-year IRA/Roth/HSA contributions and the Q4 backstop."""
    return date(tax_year + 1, 4, 15)


def _q1_estimate(tax_year: int) -> date:
    # 1st-quarter estimated payment: Apr 15 OF the tax year (IRC §6654).
    return date(tax_year, 4, 15)


def _q2_estimate(tax_year: int) -> date:
    # 2nd-quarter estimated payment: Jun 15 of the tax year.
    return date(tax_year, 6, 15)


def _q3_estimate(tax_year: int) -> date:
    # 3rd-quarter estimated payment: Sep 15 of the tax year.
    return date(tax_year, 9, 15)


def _q4_estimate(tax_year: int) -> date:
    # 4th-quarter estimated payment: Jan 15 of the year AFTER the tax year.
    return date(tax_year + 1, 1, 15)


def _dec31(tax_year: int) -> date:
    # In-year, year-end deadline (RMDs must be taken by Dec 31 of the tax year).
    return date(tax_year, 12, 31)


def _mar15(tax_year: int) -> date:
    """Mar 15 of the tax year. The §1362(b) S-corp election is due within 2
    months + 15 days of the start of the tax year it's to take effect → for a
    calendar-year entity that is Mar 15 of the tax year. Also the unextended due
    date for calendar-year passthrough returns (1120-S / 1065)."""
    return date(tax_year, 3, 15)


def _oct15_next(tax_year: int) -> date:
    """Oct 15 of the year after the tax year — the extended individual return
    due date (Form 4868) and the FBAR's automatic-extension final date."""
    return date(tax_year + 1, 10, 15)


# --------------------------------------------------------------------------- #
# The catalog. Order is the natural chase order within a season.
# --------------------------------------------------------------------------- #
STATUTORY_DEADLINES: list[StatutoryDeadline] = [
    StatutoryDeadline(
        key="q1_estimate",
        label="Q1 estimated tax payment",
        citation="IRC §6654 (Form 1040-ES)",
        resolver=_q1_estimate,
    ),
    StatutoryDeadline(
        key="q2_estimate",
        label="Q2 estimated tax payment",
        citation="IRC §6654 (Form 1040-ES)",
        resolver=_q2_estimate,
    ),
    StatutoryDeadline(
        key="q3_estimate",
        label="Q3 estimated tax payment",
        citation="IRC §6654 (Form 1040-ES)",
        resolver=_q3_estimate,
    ),
    StatutoryDeadline(
        key="q4_estimate",
        label="Q4 estimated tax payment",
        citation="IRC §6654 (Form 1040-ES)",
        resolver=_q4_estimate,
    ),
    StatutoryDeadline(
        key="ira_contribution",
        label="Traditional IRA contribution (prior year)",
        citation="IRC §219(f)(3) / §6072",
        resolver=_apr15_next,
    ),
    StatutoryDeadline(
        key="roth_contribution",
        label="Roth IRA contribution (prior year)",
        citation="IRC §408A / §219(f)(3)",
        resolver=_apr15_next,
    ),
    StatutoryDeadline(
        key="sep_ira",
        label="SEP-IRA contribution (employer)",
        # Due by the return due date INCLUDING extensions; we surface the
        # unextended date as the planning target (extend explicitly if needed).
        citation="IRC §404(h)(1)(B)",
        resolver=_apr15_next,
    ),
    StatutoryDeadline(
        key="solo_401k_employee",
        label="Solo 401(k) employee deferral",
        # Elective deferrals for a self-employed owner are effectively tied to
        # the tax-year end / W-2 timing; treat Dec 31 of the tax year as target.
        citation="IRC §401(k) / §402(g)",
        resolver=_dec31,
    ),
    StatutoryDeadline(
        key="hsa_contribution",
        label="HSA contribution (prior year)",
        citation="IRC §223(d)(4)(B)",
        resolver=_apr15_next,
    ),
    StatutoryDeadline(
        key="form_8606",
        label="File Form 8606 (nondeductible basis / conversions)",
        # Attached to the 1040; tracks the unextended individual return date.
        citation="Form 8606 (with Form 1040)",
        resolver=_apr15_next,
    ),
    StatutoryDeadline(
        key="rmd",
        label="Required minimum distribution",
        # SECURE 2.0: RMDs must be taken by Dec 31 of the tax year (first-year
        # RMD has an Apr-1 grace not modeled here; that's a per-client edge).
        citation="IRC §401(a)(9) (SECURE 2.0)",
        resolver=_dec31,
    ),
    StatutoryDeadline(
        key="scorp_election_2553",
        label="S-corporation election (Form 2553)",
        # Within 2 months and 15 days of the start of the tax year it takes
        # effect → Mar 15 for a calendar-year entity (IRC §1362(b)).
        citation="IRC §1362(b) (Form 2553)",
        resolver=_mar15,
    ),
    StatutoryDeadline(
        key="backdoor_roth",
        label="Backdoor Roth (nondeductible contribution + conversion)",
        # The nondeductible contribution leg is bounded by the IRA deadline;
        # the conversion itself is best done same-year, so target Apr 15 next.
        citation="IRC §408A(d)(3) / §219(f)(3)",
        resolver=_apr15_next,
    ),
    StatutoryDeadline(
        key="fbar",
        label="FBAR (FinCEN Form 114)",
        # Due Apr 15 with an automatic extension to Oct 15; we surface the
        # automatic-extension date as the practical deadline.
        citation="31 U.S.C. §5314 (FinCEN 114)",
        resolver=_oct15_next,
    ),
    StatutoryDeadline(
        key="extension_1040",
        label="File extension (Form 4868)",
        # The extension request itself is due on the unextended return date.
        citation="IRC §6081 (Form 4868)",
        resolver=_apr15_next,
    ),
]

# key -> entry, for O(1) resolution.
_BY_KEY: dict[str, StatutoryDeadline] = {entry.key: entry for entry in STATUTORY_DEADLINES}


def resolve_deadline(key: str, tax_year: int) -> date | None:
    """The calendar date for ``key`` in ``tax_year``, or None for an unknown key.

    Unknown keys return None rather than raising so a free-standing task that
    carries an advisor-typed ``statutory_key`` we don't recognize still saves
    (it just won't auto-resolve a date)."""
    entry = _BY_KEY.get(key)
    return entry.resolver(tax_year) if entry is not None else None


def list_statutory_deadlines(tax_year: int) -> list[dict[str, object]]:
    """The whole catalog resolved for ``tax_year`` — each entry as
    ``{key, label, citation, due_date}`` in chase order."""
    return [
        {
            "key": entry.key,
            "label": entry.label,
            "citation": entry.citation,
            "due_date": entry.resolver(tax_year),
        }
        for entry in STATUTORY_DEADLINES
    ]
