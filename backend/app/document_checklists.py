"""Static, code-side catalog of the documents a tax PLANNER needs per entity type.

This is reference data, not an engine: a frozen table that answers the "I don't
know what's needed" question. For each entity type it lists the documents an
advisor genuinely needs to PLAN (project the year, size levers, check thresholds)
— deliberately a planning, not a filing, lens. The two distinctions that drive
every list:

  * Planning leans on the PRIOR-YEAR return (the baseline we project from), the
    CURRENT-YEAR interim financials / P&L (what the year actually looks like so
    far), and proof of estimated payments already made — none of which a pure
    "file last year's return" checklist emphasizes.
  * Each entity carries its own structural records: an S-corp's shareholder
    basis + reasonable-comp support, a C-corp's fixed-asset/depreciation schedule
    and owner-W-2 payroll, a partnership's K-1s + capital accounts, an
    individual's W-2/1099/1098 wage-and-information returns.

Every item cites a ``form_or_source`` (an IRS form number where one exists, or a
named record like "depreciation schedule (Form 4562 detail)") and a one-sentence
plain-English ``why``. Sources: IRS form instructions (1040/1065/1120/1120-S,
Schedules K-1, Forms 4562/7203) and AICPA return-prep checklists; this is
well-established practice, not invented requirements.

The catalog is intentionally static (no DB, no engine): the intake surface and
the ``/intake/document-checklist`` endpoint both resolve names/labels/why from
here so a non-expert can see, per entity, exactly what to gather before planning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# --------------------------------------------------------------------------- #
# The shape of one catalog row.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Doc:
    """One document a planner asks for.

    ``name`` is a short human label; ``form_or_source`` is the IRS form number or
    the named record it comes from (what the client physically hands over); ``why``
    is a single plain-English sentence on why a *planner* (not just a filer) needs
    it. Serialized to the API verbatim via :func:`checklist_for`.
    """

    name: str
    form_or_source: str
    why: str


@dataclass(frozen=True)
class EntityType:
    """A pickable entity type: a stable ``key``, a human ``label``, and a
    one-line plain-language ``description`` for the picker / "not sure" explainer."""

    key: str
    label: str
    description: str


# --------------------------------------------------------------------------- #
# The entity types the picker offers. Keys are the contract used by the API and
# the frontend; order is the natural "simplest → most complex" reading order.
# `not_sure` is a UX affordance (it has no checklist of its own — the surface
# shows the descriptions so the user can self-identify), so it is NOT in
# DOCUMENT_CHECKLISTS and `checklist_for("not_sure")` raises like any unknown key.
# --------------------------------------------------------------------------- #
ENTITY_TYPES: list[EntityType] = [
    EntityType(
        key="individual",
        label="Individual (personal taxes)",
        description="You file a personal Form 1040 — wages, investments, maybe a rental, but no business of your own.",
    ),
    EntityType(
        key="sole_prop",
        label="Sole proprietor / single-member LLC",
        description="You run a business by yourself and report it on Schedule C of your personal 1040 (a single-member LLC files the same way by default).",
    ),
    EntityType(
        key="partnership",
        label="Partnership / multi-member LLC",
        description="Two or more owners share a business that files Form 1065 and issues each owner a Schedule K-1.",
    ),
    EntityType(
        key="s_corp",
        label="S corporation",
        description="A corporation (or LLC) that elected S status, files Form 1120-S, pays owners a salary, and passes profit through on K-1s.",
    ),
    EntityType(
        key="c_corp",
        label="C corporation",
        description="A corporation that files and pays its own tax on Form 1120 — separate from your personal return.",
    ),
    EntityType(
        key="multi_entity",
        label="Several entities / a business owner",
        description="You own more than one of the above — e.g. an operating S-corp plus a rental LLC — and want them planned together.",
    ),
    EntityType(
        key="not_sure",
        label="I'm not sure",
        description="Not sure which one fits? Pick this and we'll explain the choices in plain language, then point you to what to gather.",
    ),
]

_ENTITY_LABELS: dict[str, str] = {e.key: e.label for e in ENTITY_TYPES}


# --------------------------------------------------------------------------- #
# The catalog. One entry per planning-capable entity type, each with a
# `required` list (you genuinely can't plan without it) and a `beneficial` list
# (sharpens the plan). `not_sure` is deliberately absent.
# --------------------------------------------------------------------------- #
DOCUMENT_CHECKLISTS: dict[str, dict[str, list[Doc]]] = {
    # ----------------------------------------------------------------- #
    # INDIVIDUAL — Form 1040
    # ----------------------------------------------------------------- #
    "individual": {
        "required": [
            Doc(
                name="Last year's federal return",
                form_or_source="prior-year Form 1040 (with all schedules)",
                why="It's the baseline we project this year from — carryovers, elections, and last year's effective rate all start here.",
            ),
            Doc(
                name="Wage statements",
                form_or_source="Form W-2 (all employers)",
                why="Sets your wage income and the tax already withheld, which drives whether you're over- or under-paid for the year.",
            ),
            Doc(
                name="Interest & dividend income",
                form_or_source="Forms 1099-INT / 1099-DIV",
                why="Qualified vs. ordinary dividends and taxable interest change your bracket and what investment moves make sense.",
            ),
            Doc(
                name="Brokerage / investment activity",
                form_or_source="Form 1099-B or year-end brokerage composite 1099",
                why="Realized gains and losses determine room for tax-loss harvesting and how a 0%/15%/20% capital-gains bracket plays out.",
            ),
            Doc(
                name="Other income statements",
                form_or_source="Forms 1099-NEC / 1099-MISC / 1099-K / 1099-R / SSA-1099",
                why="Self-employment, retirement distributions, and Social Security each carry their own planning levers and thresholds.",
            ),
            Doc(
                name="Pass-through income you receive",
                form_or_source="Schedule K-1 (from any partnership, S-corp, estate, or trust)",
                why="K-1 income flows onto your 1040 and affects QBI, basis, and which entity-level moves help you personally.",
            ),
            Doc(
                name="Mortgage interest & property tax",
                form_or_source="Form 1098 + property-tax bills",
                why="Tells us whether you itemize or take the standard deduction — the fork that governs most personal strategies.",
            ),
        ],
        "beneficial": [
            Doc(
                name="Estimated tax payments made",
                form_or_source="Form 1040-ES vouchers / IRS payment records",
                why="Knowing what you've already paid lets us right-size the remaining quarterly payments and avoid an underpayment penalty.",
            ),
            Doc(
                name="Retirement & HSA contributions",
                form_or_source="Form 5498 / plan & payroll statements",
                why="Shows how much deduction room is left in IRAs, 401(k)s, and HSAs — usually the highest-leverage move available.",
            ),
            Doc(
                name="Charitable giving records",
                form_or_source="donation receipts / acknowledgment letters",
                why="Lets us model bunching, a donor-advised fund, or a QCD instead of scattered annual gifts.",
            ),
            Doc(
                name="Tuition & student-loan statements",
                form_or_source="Forms 1098-T / 1098-E",
                why="Education credits and the student-loan-interest deduction phase out by income, so they shape the plan.",
            ),
            Doc(
                name="Year-end pay stub",
                form_or_source="final paycheck of the year",
                why="Captures current withholding and pre-tax benefits so we can project the full year before the W-2 arrives.",
            ),
        ],
    },
    # ----------------------------------------------------------------- #
    # SOLE PROP / SINGLE-MEMBER LLC — Schedule C on the 1040
    # ----------------------------------------------------------------- #
    "sole_prop": {
        "required": [
            Doc(
                name="Last year's personal return",
                form_or_source="prior-year Form 1040 with Schedule C",
                why="The baseline for this year and the source of any prior depreciation, home-office, or loss carryovers.",
            ),
            Doc(
                name="Year-to-date profit & loss",
                form_or_source="current-year P&L / income statement",
                why="Planning needs how the business is actually doing this year, not just last year's filed numbers, to project tax.",
            ),
            Doc(
                name="Business income records",
                form_or_source="Forms 1099-NEC / 1099-K + sales/bookkeeping totals",
                why="Establishes gross receipts — the base for self-employment tax, QBI, and any S-corp-election analysis.",
            ),
            Doc(
                name="Business expense detail",
                form_or_source="bookkeeping export / expense ledger by category",
                why="Net profit drives SE tax and QBI, and the category mix surfaces deductions (retirement, health, vehicle) you may be missing.",
            ),
            Doc(
                name="Asset & depreciation schedule",
                form_or_source="depreciation schedule (Form 4562 detail)",
                why="Shows remaining basis and lets us weigh Section 179 / bonus depreciation against spreading deductions over future years.",
            ),
            Doc(
                name="Estimated tax payments made",
                form_or_source="Form 1040-ES vouchers / IRS payment records",
                why="Self-employed income isn't withheld, so we must know what's been paid to set the remaining quarterly payments correctly.",
            ),
        ],
        "beneficial": [
            Doc(
                name="Self-employed retirement statements",
                form_or_source="SEP-IRA / Solo-401(k) plan statements",
                why="These plans allow far larger deductible contributions than an IRA and are the biggest lever for a profitable sole prop.",
            ),
            Doc(
                name="Health-insurance premiums",
                form_or_source="self-employed health-insurance statements (Form 1095)",
                why="Self-employed health premiums are an above-the-line deduction we can plan around your net profit.",
            ),
            Doc(
                name="Home-office & vehicle records",
                form_or_source="square-footage / mileage logs",
                why="Lets us choose the method (actual vs. simplified, standard mileage vs. actual) that produces the larger deduction.",
            ),
            Doc(
                name="Payroll records (if you have employees)",
                form_or_source="Forms 941 / W-3 / payroll summary",
                why="Wages and payroll taxes affect QBI and tell us whether an S-corp election would actually save money at your profit level.",
            ),
        ],
    },
    # ----------------------------------------------------------------- #
    # PARTNERSHIP / MULTI-MEMBER LLC — Form 1065 + K-1s
    # ----------------------------------------------------------------- #
    "partnership": {
        "required": [
            Doc(
                name="Last year's partnership return",
                form_or_source="prior-year Form 1065 (complete, with statements)",
                why="The baseline for projections and the source of elections, carryovers, and the partnership's accounting method.",
            ),
            Doc(
                name="Partner K-1s issued",
                form_or_source="Schedule K-1 (Form 1065) for each partner",
                why="Shows how income and deductions split among partners — essential to plan at both the entity and the individual level.",
            ),
            Doc(
                name="Year-to-date financial statements",
                form_or_source="current-year P&L + balance sheet",
                why="Planning needs the live picture of income, expenses, and the balance sheet (Schedule L) to project the year.",
            ),
            Doc(
                name="Partner capital accounts",
                form_or_source="capital-account rollforward (tax basis)",
                why="Outside/inside basis governs whether losses are deductible and whether distributions are tax-free, so it gates most moves.",
            ),
            Doc(
                name="Guaranteed payments & distributions",
                form_or_source="partnership ledger / agreement schedule",
                why="Guaranteed payments are taxed differently from distributions, and rebalancing them is a common planning lever.",
            ),
            Doc(
                name="Asset & depreciation schedule",
                form_or_source="depreciation schedule (Form 4562 detail)",
                why="Drives Section 179 / bonus-depreciation timing and shows remaining basis on the partnership's fixed assets.",
            ),
        ],
        "beneficial": [
            Doc(
                name="Partnership / operating agreement",
                form_or_source="partnership or LLC operating agreement",
                why="Special allocations and profit/loss splits must respect the agreement, which shapes what allocations we can plan.",
            ),
            Doc(
                name="Partner debt & at-risk detail",
                form_or_source="loan schedules / liability allocation",
                why="Recourse vs. nonrecourse debt changes each partner's basis and at-risk amount, and therefore deductible losses.",
            ),
            Doc(
                name="Section 754 election status",
                form_or_source="prior elections / step-up records",
                why="A 754 election affects basis on transfers and distributions, which matters when ownership is changing.",
            ),
            Doc(
                name="State apportionment data",
                form_or_source="state K-1s / nexus & apportionment workpapers",
                why="Multi-state partners need apportionment to plan state tax and any pass-through-entity (PTET) elections.",
            ),
        ],
    },
    # ----------------------------------------------------------------- #
    # S CORPORATION — Form 1120-S + K-1s
    # ----------------------------------------------------------------- #
    "s_corp": {
        "required": [
            Doc(
                name="Last year's S-corp return",
                form_or_source="prior-year Form 1120-S (complete, with statements)",
                why="The baseline for projections and the source of elections, carryovers, and the corporation's accounting method.",
            ),
            Doc(
                name="Shareholder K-1s issued",
                form_or_source="Schedule K-1 (Form 1120-S) for each shareholder",
                why="Shows the pass-through split each owner reports personally — needed to plan at both the entity and individual level.",
            ),
            Doc(
                name="Officer / owner compensation",
                form_or_source="owner Form W-2 + payroll reports (Forms 941 / W-3)",
                why="Reasonable owner salary is the single biggest S-corp lever; too low invites IRS recharacterization, too high wastes payroll tax.",
            ),
            Doc(
                name="Shareholder stock & debt basis",
                form_or_source="Form 7203 / basis schedule per shareholder",
                why="Basis caps how much loss a shareholder can deduct and whether distributions are tax-free, so it gates most planning.",
            ),
            Doc(
                name="Year-to-date financial statements",
                form_or_source="current-year P&L + balance sheet",
                why="Planning needs the live income, expense, and balance-sheet (Schedule L) picture to project the year's tax.",
            ),
            Doc(
                name="Asset & depreciation schedule",
                form_or_source="depreciation schedule (Form 4562 detail)",
                why="Drives Section 179 / bonus-depreciation timing and shows remaining basis on the corporation's fixed assets.",
            ),
        ],
        "beneficial": [
            Doc(
                name="Reasonable-compensation support",
                form_or_source="comp study / industry-wage benchmark",
                why="Documentation defending the owner salary protects the salary/distribution split if the IRS ever questions it.",
            ),
            Doc(
                name="Accountable plan & owner reimbursements",
                form_or_source="reimbursement policy / expense reports",
                why="Reimbursing owner expenses (home office, mileage, health) through an accountable plan is deductible and avoids extra payroll tax.",
            ),
            Doc(
                name="2%-shareholder health insurance",
                form_or_source="payroll detail showing health premiums in W-2 Box 1",
                why="Owner health premiums must run through payroll to be deductible, and getting this right preserves the self-employed health deduction.",
            ),
            Doc(
                name="Retirement plan documents",
                form_or_source="401(k) / SEP plan statements + census",
                why="Plan type and owner deferrals interact with the W-2 salary, so we size contributions against the comp decision.",
            ),
            Doc(
                name="S-election & prior C-corp history",
                form_or_source="Form 2553 + any prior C-corp earnings (E&P) records",
                why="Built-in gains and accumulated E&P from a former C-corp can create traps a planner must steer around.",
            ),
        ],
    },
    # ----------------------------------------------------------------- #
    # C CORPORATION — Form 1120
    # ----------------------------------------------------------------- #
    "c_corp": {
        "required": [
            Doc(
                name="Last year's corporate return",
                form_or_source="prior-year Form 1120 (federal, complete)",
                why="The baseline for projections and the source of NOL carryovers, credits, elections, and the accounting method.",
            ),
            Doc(
                name="Financial statements",
                form_or_source="current-year P&L + balance sheet",
                why="The corporation pays its own tax, so projecting the year needs live income, expenses, and the Schedule L balance sheet.",
            ),
            Doc(
                name="Fixed-asset & depreciation schedule",
                form_or_source="depreciation schedule (Form 4562 detail)",
                why="Drives Section 179 / bonus-depreciation timing and tracks remaining basis on the company's assets.",
            ),
            Doc(
                name="Payroll records incl. owner W-2",
                form_or_source="Forms 941 / W-3 + officer-compensation report",
                why="Officer pay is a separate 1120 line and a primary lever for balancing salary, bonus, and retained earnings against the corporate rate.",
            ),
            Doc(
                name="Estimated tax payments made",
                form_or_source="Form 1120-W / EFTPS payment records",
                why="C-corps owe their own quarterly estimates, so we must know what's been paid to set the remaining payments and avoid penalties.",
            ),
            Doc(
                name="State corporate return(s)",
                form_or_source="prior-year state Form 1120 / franchise return",
                why="State corporate and franchise tax (and apportionment) materially change the all-in rate the plan optimizes against.",
            ),
        ],
        "beneficial": [
            Doc(
                name="Shareholder & dividend records",
                form_or_source="distribution ledger / Forms 1099-DIV",
                why="Lets us weigh salary vs. dividend and watch for double taxation and any accumulated-earnings exposure.",
            ),
            Doc(
                name="NOL & credit carryforward detail",
                form_or_source="carryforward schedules (NOL, general business credits)",
                why="Knowing carryforwards lets us time income and deductions to actually use them before they're limited.",
            ),
            Doc(
                name="Owner loans & related-party agreements",
                form_or_source="loan notes / related-party contracts",
                why="Loans to or from owners must carry adequate interest and terms, or the IRS can recast them — a planning trap to manage.",
            ),
            Doc(
                name="Fringe-benefit & retirement plans",
                form_or_source="benefit plan documents / 401(k) statements",
                why="C-corps can deduct a broader set of owner fringe benefits, which is a distinctive lever worth sizing.",
            ),
            Doc(
                name="R&D / capital-expenditure detail",
                form_or_source="project ledgers / capex schedule",
                why="Surfaces credits (R&D) and §174 treatment plus timing of capital spending that move the corporate bill.",
            ),
        ],
    },
    # ----------------------------------------------------------------- #
    # MULTI-ENTITY — an owner with several entities, planned together
    # ----------------------------------------------------------------- #
    "multi_entity": {
        "required": [
            Doc(
                name="Owner's personal return",
                form_or_source="prior-year Form 1040 (with all K-1s)",
                why="The personal return is where every entity's pass-through income lands, so it anchors the whole plan.",
            ),
            Doc(
                name="Each entity's last return",
                form_or_source="prior-year 1065 / 1120-S / 1120 per entity",
                why="We can't plan the group without each entity's baseline, elections, and carryovers.",
            ),
            Doc(
                name="All K-1s you receive",
                form_or_source="Schedule K-1 from every partnership and S-corp",
                why="The K-1s show how each entity flows to you personally — the key to coordinating moves across them.",
            ),
            Doc(
                name="Year-to-date financials per entity",
                form_or_source="current-year P&L + balance sheet for each",
                why="Live numbers for each business let us project the combined year and shift income/deductions to the best entity.",
            ),
            Doc(
                name="Basis schedules per entity",
                form_or_source="Form 7203 / partner & shareholder basis worksheets",
                why="Basis differs by entity and caps losses and tax-free distributions, so each one gates what we can plan there.",
            ),
            Doc(
                name="Ownership & org structure",
                form_or_source="org chart / ownership-percentage schedule",
                why="Who owns what (and any holding structure) determines aggregation, related-party rules, and where to place income.",
            ),
            Doc(
                name="Inter-company transactions",
                form_or_source="management-fee / rent / loan agreements between entities",
                why="Payments between your entities must be at arm's length and shift tax between them — a core multi-entity lever and trap.",
            ),
        ],
        "beneficial": [
            Doc(
                name="Combined depreciation schedules",
                form_or_source="Form 4562 detail across all entities",
                why="Seeing all fixed assets together lets us place Section 179 / bonus where it does the most good across the group.",
            ),
            Doc(
                name="Group payroll & retirement plans",
                form_or_source="payroll summaries + plan documents",
                why="Controlled-group and affiliated-service rules can link plans across entities, which constrains and shapes contributions.",
            ),
            Doc(
                name="State footprint & apportionment",
                form_or_source="state returns / nexus & PTET workpapers",
                why="Multiple entities often mean multiple states; apportionment and PTET elections are significant coordinated levers.",
            ),
            Doc(
                name="Estimated payments across entities",
                form_or_source="1040-ES + 1120-W / EFTPS records",
                why="Coordinating estimates across the owner and the entities prevents both penalties and idle overpayments.",
            ),
        ],
    },
}


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #
def entity_types() -> list[dict[str, str]]:
    """The pickable entity types as ``{key, label, description}`` (picker order)."""
    return [asdict(e) for e in ENTITY_TYPES]


def checklist_for(entity_type: str) -> dict[str, object]:
    """The full checklist for ``entity_type`` as a plain serializable dict::

        {entity_type, label, required: [{name, form_or_source, why}, ...],
         beneficial: [...]}

    Raises :class:`KeyError` for an unknown / non-planning entity type (e.g.
    ``"not_sure"``), so the API layer can translate it to a 422.
    """
    entry = DOCUMENT_CHECKLISTS[entity_type]  # KeyError → unknown type
    return {
        "entity_type": entity_type,
        "label": _ENTITY_LABELS.get(entity_type, entity_type),
        "required": [asdict(d) for d in entry["required"]],
        "beneficial": [asdict(d) for d in entry["beneficial"]],
    }
