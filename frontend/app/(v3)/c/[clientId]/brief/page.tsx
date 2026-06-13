"use client";

// Surface 09 — THE BRIEF
// The captured planning context that turns a calculator into counsel.
// Three zones: the decade timeline (event nodes + tax-shadow bands), the
// captured brief (structured editable lines from ClientPlanningProfile),
// and the goal→finding wiring panel (the BECAUSE map from strategist findings).
//
// Data:
//   [live]     GET /clients/{id}/planning-profile  — the profile struct
//   [live]     PUT /clients/{id}/planning-profile  — save edits
//   [live]     Strategist findings via overview.strategies (goal links rendered
//              from disposition + name)
//   [additive] shadow derivation from multiyear/state engines
//   [additive] priced questions (re-run only affected exhibits after answer)
//
// ENGINE-ONLY NUMBERS: every figure on screen comes from an API field.
// Priced-question `worth` amounts are [additive] — the endpoint does not exist
// yet; the section renders an honest empty-state until it lands.
// TODO(integration: GET /clients/{id}/planning-questions)

import { useCallback, useEffect, useState } from "react";
import { Pencil, Check, X } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  MiniButton,
  Aavatar,
  Omnibar,
  Term,
} from "@/components/kit";

/* ---- the planning-profile shape (matches backend GET /clients/{id}/planning-profile) ---- */
interface Profile {
  primary_objective: string | null;
  retirement_target_year: number | null;
  liquidity_event: string | null;
  liquidity_event_year: number | null;
  liquidity_event_amount_cents: number | null;
  charitable_intent: string | null;
  annual_giving_cents: number | null;
  estate_priority: string | null;
  planned_relocation_state: string | null;
  relocation_year: number | null;
  roth_preference: string | null;
  risk_tolerance: string | null;
  cash_flow_sensitivity: string | null;
  education_funding: boolean | null;
  business_succession: string | null;
  notes: string | null;
}

const EMPTY_PROFILE: Profile = {
  primary_objective: null,
  retirement_target_year: null,
  liquidity_event: null,
  liquidity_event_year: null,
  liquidity_event_amount_cents: null,
  charitable_intent: null,
  annual_giving_cents: null,
  estate_priority: null,
  planned_relocation_state: null,
  relocation_year: null,
  roth_preference: null,
  risk_tolerance: null,
  cash_flow_sensitivity: null,
  education_funding: null,
  business_succession: null,
  notes: null,
};

/* ---- human-readable labels for enum fields ---- */
const OBJECTIVE_LABELS: Record<string, string> = {
  no_preference: "No stated preference",
  minimize_current_tax: "Minimize current-year tax",
  minimize_lifetime_tax: "Minimize lifetime tax",
  maximize_retirement: "Maximize retirement readiness",
  wealth_transfer: "Transfer wealth to heirs",
  charitable_legacy: "Build a charitable legacy",
};
const LIQUIDITY_LABELS: Record<string, string> = {
  none: "None expected",
  business_sale: "Business sale",
  equity_compensation: "Equity comp / RSU vesting",
  real_estate: "Real-estate sale",
  inheritance: "Inheritance",
  other: "Other",
};
const CHARITABLE_LABELS: Record<string, string> = {
  none: "None",
  low: "Low intent",
  moderate: "Moderate intent",
  high: "High intent",
  legacy: "Legacy giving",
};
const ROTH_LABELS: Record<string, string> = {
  no_preference: "No preference",
  prefer_roth: "Roth-preferring",
  prefer_traditional: "Prefer traditional",
  advisor_optimize: "Let advisor optimize",
};
const RISK_LABELS: Record<string, string> = {
  conservative: "Conservative",
  moderate: "Moderate",
  aggressive: "Aggressive",
};
const CASHFLOW_LABELS: Record<string, string> = {
  low: "Low (can defer)",
  medium: "Medium · flexible",
  high: "High (needs liquidity)",
};
const SUCCESSION_LABELS: Record<string, string> = {
  none: "None / n-a",
  sell_external: "Sell to outside buyer",
  transfer_family: "Transfer to family",
  esop: "ESOP",
  undecided: "Undecided",
};

function readableLabel(map: Record<string, string>, val: string | null | undefined): string | null {
  if (!val || val === "none" || val === "no_preference") return null;
  return map[val] ?? val;
}

/* ============================================================== component == */

export default function BriefPage() {
  const { clientId, overview, loading: overviewLoading } = useClientOverview();
  const [profile, setProfile] = useState<Profile>(EMPTY_PROFILE);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Profile>(EMPTY_PROFILE);
  const [saved, setSaved] = useState(false);

  /* ---- load the planning profile [live: GET /clients/{id}/planning-profile] ---- */
  const loadProfile = useCallback(() => {
    if (!clientId) return;
    api
      .get(`/clients/${clientId}/planning-profile`)
      .then((r) => {
        const p: Profile = { ...EMPTY_PROFILE, ...r.data };
        setProfile(p);
        setDraft(p);
      })
      .catch(() => undefined)
      .finally(() => setProfileLoaded(true));
  }, [clientId]);

  useEffect(loadProfile, [loadProfile]);

  /* ---- save [live: PUT /clients/{id}/planning-profile] ---- */
  const save = useAction(async () => {
    if (!clientId) return;
    await api.put(`/clients/${clientId}/planning-profile`, draft);
    setProfile(draft);
    setSaved(true);
    setEditing(false);
  });

  function beginEdit() {
    setDraft({ ...profile });
    setSaved(false);
    setEditing(true);
  }
  function cancelEdit() {
    setDraft({ ...profile });
    setEditing(false);
  }
  function setProp<K extends keyof Profile>(k: K, v: Profile[K]) {
    setSaved(false);
    setDraft((prev) => ({ ...prev, [k]: v }));
  }

  /* ---- goal→finding wiring: live from overview.strategies ---- */
  const goalLinks = (overview?.strategies ?? [])
    .filter((s) => s.name && s.disposition && s.disposition !== "declined")
    .slice(0, 6);

  if (overviewLoading || !profileLoaded) {
    return (
      <div className="wrap py-7">
        <div className="skeleton h-[80px] w-full rounded-[14px]" />
        <div className="mt-[22px] skeleton h-[280px] w-full rounded-[14px]" />
        <div className="mt-[22px] grid gap-[22px] lg:grid-cols-[1fr_1.25fr]">
          <div className="skeleton h-[280px] rounded-[14px]" />
          <div className="skeleton h-[340px] rounded-[14px]" />
        </div>
      </div>
    );
  }

  const p = editing ? draft : profile;
  const client = overview?.client;

  /* ---- derive the brief summary lines from profile fields (no fabrication — these
         are all direct API value→label mappings) ---- */
  const objectiveText = readableLabel(OBJECTIVE_LABELS, p.primary_objective);
  const liquidityText =
    p.liquidity_event && p.liquidity_event !== "none"
      ? [
          LIQUIDITY_LABELS[p.liquidity_event] ?? p.liquidity_event,
          p.liquidity_event_year != null ? String(p.liquidity_event_year) : null,
          p.liquidity_event_amount_cents != null
            ? `≈ ${centsToUSD(p.liquidity_event_amount_cents)}`
            : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;
  const relocationText = p.planned_relocation_state
    ? [p.planned_relocation_state, p.relocation_year != null ? String(p.relocation_year) : null]
        .filter(Boolean)
        .join(" · ")
    : null;
  const charitableText = readableLabel(CHARITABLE_LABELS, p.charitable_intent);
  const charitableSubNote =
    charitableText && p.annual_giving_cents != null
      ? `~${centsToUSD(p.annual_giving_cents)}/yr`
      : null;
  const retirementText =
    p.retirement_target_year != null
      ? [
          `${p.retirement_target_year} target`,
          readableLabel(ROTH_LABELS, p.roth_preference),
        ]
          .filter(Boolean)
          .join(" · ")
      : readableLabel(ROTH_LABELS, p.roth_preference);
  const riskText = [
    readableLabel(RISK_LABELS, p.risk_tolerance),
    readableLabel(CASHFLOW_LABELS, p.cash_flow_sensitivity),
  ]
    .filter(Boolean)
    .join(" · ") || null;
  const educationText = p.education_funding ? "Education funding — 529 candidate" : null;
  const successionText = readableLabel(SUCCESSION_LABELS, p.business_succession);
  const notesText = p.notes || null;

  const hasAnyBrief =
    objectiveText ||
    liquidityText ||
    relocationText ||
    charitableText ||
    retirementText ||
    riskText ||
    educationText ||
    successionText ||
    notesText;

  return (
    <div className="wrap py-7 pb-16">
      {/* ---- header ---- */}
      <section className="rise flex flex-wrap items-baseline gap-[14px]">
        <h1 className="m-0 text-[30px] font-extrabold leading-none tracking-[-0.02em]">The Brief</h1>
        <Annotation className="!text-[14px]">
          what {client?.display_name ?? "the client"} actually wants — the context that turns a
          calculator into counsel
        </Annotation>
        <div className="ml-auto">
          <Chip tone="agent">strategist re-reads this before every run</Chip>
        </div>
      </section>

      {/* ======================================================== the timeline ======= */}
      <Panel className="rise d1 relative mt-[22px] overflow-x-auto pb-[80px]">
        <PanelHead style={{ border: 0, paddingBottom: "8px" }}>
          <MicroLabel>The decade · events and the tax shadows they cast</MicroLabel>
          <span className="ml-auto">
            <Chip>derived from the brief below</Chip>
          </span>
        </PanelHead>

        <Timeline profile={p} />

        <div className="mt-3 px-[30px] font-mono text-[9.5px] text-[var(--g-ink-3)]">
          {/* TODO(integration: GET /clients/{id}/timeline-shadows) */}
          <span className="tone-cost mr-1">[additive]</span>
          Shadow bands (residency clock, Roth valley, IRMAA lookback) are derived from the multiyear +
          state engines — shown as labeled placeholders until the shadow-derivation endpoint lands.
        </div>
      </Panel>

      {/* ======================================================== two-col grid ======= */}
      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1fr_1.25fr]">
        <div className="flex flex-col gap-[22px]">
          {/* ---- the captured brief ---- */}
          <Panel className="rise d2">
            <PanelHead>
              <MicroLabel>Captured · planning profile</MicroLabel>
              <div className="ml-auto flex items-center gap-2">
                {editing ? (
                  <>
                    {save.error ? (
                      <span className="font-mono text-[10px] tone-cost">{save.error}</span>
                    ) : null}
                    <MiniButton onClick={cancelEdit} disabled={save.pending}>
                      <X className="inline h-3 w-3" /> Cancel
                    </MiniButton>
                    <MiniButton go onClick={() => void save.run()} disabled={save.pending}>
                      {save.pending ? "Saving…" : (
                        <><Check className="inline h-3 w-3 mr-0.5" /> Save</>
                      )}
                    </MiniButton>
                  </>
                ) : (
                  <MiniButton onClick={beginEdit}>
                    <Pencil className="inline h-3 w-3 mr-0.5" /> edit
                  </MiniButton>
                )}
              </div>
            </PanelHead>

            {!hasAnyBrief && !editing ? (
              <EmptyBriefState onEdit={beginEdit} clientName={client?.display_name} />
            ) : editing ? (
              <EditForm draft={draft} setProp={setProp} />
            ) : (
              <ReadBrief
                objective={objectiveText}
                liquidity={liquidityText}
                relocation={relocationText}
                charitable={charitableText}
                charitableSubNote={charitableSubNote}
                retirement={retirementText}
                risk={riskText}
                education={educationText}
                succession={successionText}
                notes={notesText}
                saved={saved}
              />
            )}
          </Panel>

          {/* ---- goal → finding wiring (the BECAUSE map) ---- */}
          <Panel className="rise d3">
            <PanelHead>
              <MicroLabel>How the brief steers the memo</MicroLabel>
            </PanelHead>
            {goalLinks.length > 0 ? (
              <>
                <div className="grid grid-cols-[1fr_26px_1fr] items-center gap-x-0 gap-y-1.5 px-[18px] py-[14px]">
                  {goalLinks.map((s) => (
                    <GoalFindingRow
                      key={s.id}
                      goal={briefKeyForStrategy(s.name, s.category)}
                      finding={s.name}
                      disposition={s.disposition}
                    />
                  ))}
                </div>
                <div className="border-t border-[var(--g-hairline-soft)] px-[18px] py-[14px] text-[12px] text-[var(--g-ink-3)]">
                  Every memo finding carries its BECAUSE line back to one of these. No goal, no
                  speculation — the agent doesn&apos;t invent priorities.
                </div>
              </>
            ) : (
              <div className="px-[18px] py-[18px]">
                <div className="flex items-start gap-3">
                  <Aavatar name="Strategist" agent="strategist" idle />
                  <div>
                    <p className="text-[13px] leading-relaxed text-[var(--g-ink-2)]">
                      Once you run an analysis, every strategist finding will be wired back to a
                      goal captured here. No goal, no speculation — the agent doesn&apos;t invent
                      priorities.
                    </p>
                    <p className="mt-2 font-mono text-[10px] text-[var(--g-ink-3)]">
                      Goal→finding links come from <code>overview.strategies</code> once the
                      strategist runs.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        </div>

        {/* ---- priced questions [additive] ---- */}
        <Panel className="rise d3">
          <PanelHead>
            <MicroLabel className="tone-cost">Questions worth money · open</MicroLabel>
            <Annotation className="!text-[13px]">
              no questionnaire walls — each ask shows the dollars it unlocks
            </Annotation>
          </PanelHead>

          {/* [additive] — TODO(integration: GET /clients/{id}/planning-questions)
              These are generated server-side when an engine input is missing/unverified;
              `worth` = the finding value the missing input gates; answering re-runs
              only the affected exhibits. Until the endpoint exists, this section renders
              an honest empty state. */}
          <div className="px-[18px] py-[18px]">
            <div className="flex items-start gap-3">
              <Aavatar name="Strategist" agent="strategist" idle />
              <div>
                <p className="text-[13px] leading-relaxed text-[var(--g-ink-2)]">
                  Priced questions are generated when an engine input is missing or
                  unverified — each ask shows exactly which finding value it gates, and
                  answering re-runs only the affected exhibits.
                </p>
                <p className="mt-3 text-[12px] text-[var(--g-ink-3)]">
                  Run the strategist to surface what gaps are worth answering on this file.
                </p>
              </div>
            </div>
            <div className="mt-5 border-t border-[var(--g-hairline-soft)] pt-3 font-mono text-[9.5px] text-[var(--g-ink-3)]">
              <span className="tone-cost">[additive]</span> Questions endpoint not yet live —
              answers will re-run only the affected exhibits (spec §7-09).
            </div>
          </div>
        </Panel>
      </div>

      {/* ---- the omnibar (door 2) ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about this client's goals…" />
      </div>
    </div>
  );
}

/* ============================================================== sub-components == */

/* ---- the decade timeline ---- */
interface TlEvent {
  year: number;
  label: string;
  sub: string;
  major?: boolean;
}

function Timeline({ profile }: { profile: Profile }) {
  // Events are derived from the planning profile fields — no fabricated numbers.
  // Shadow bands (CA residency clock, Roth valley, IRMAA lookback) are [additive]:
  // TODO(integration: GET /clients/{id}/timeline-shadows)
  // rendered as labeled placeholders until the engine provides the band boundaries.

  const currentYear = new Date().getFullYear();
  const events: TlEvent[] = [];

  events.push({ year: currentYear, label: "Today", sub: `${currentYear} plan year` });

  if (profile.liquidity_event && profile.liquidity_event !== "none" && profile.liquidity_event_year != null) {
    const liqLabel = LIQUIDITY_LABELS[profile.liquidity_event] ?? profile.liquidity_event;
    const amountPart =
      profile.liquidity_event_amount_cents != null
        ? centsToUSD(profile.liquidity_event_amount_cents)
        : null;
    events.push({
      year: profile.liquidity_event_year,
      label: liqLabel,
      sub: amountPart ?? "",
      major: true,
    });
  }

  if (profile.planned_relocation_state && profile.relocation_year != null) {
    events.push({
      year: profile.relocation_year,
      label: profile.planned_relocation_state,
      sub: "relocation · domicile established",
    });
  }

  if (profile.retirement_target_year != null) {
    events.push({
      year: profile.retirement_target_year,
      label: "Retire",
      sub:
        profile.roth_preference === "prefer_roth"
          ? "income floor drops · conversions finish"
          : "income floor drops",
    });
  }

  const sorted = [...events].sort((a, b) => a.year - b.year);

  if (sorted.length <= 1) {
    return (
      <div className="px-[30px] pb-[16px] text-[13px] text-[var(--g-ink-3)]">
        Add events to the brief — liquidity event, relocation, or retirement year — to see the
        decade view.
      </div>
    );
  }

  const minYear = sorted[0].year;
  const maxYear = Math.max(sorted[sorted.length - 1].year, currentYear + 6);
  const span = Math.max(maxYear - minYear, 1);
  const pct = (yr: number) => ((yr - minYear) / span) * 100;

  // Shadow band boundaries from profile (additive — position only)
  const relYear = profile.relocation_year;
  const retYear = profile.retirement_target_year;
  const showResidencyBand =
    profile.planned_relocation_state != null && relYear != null;
  const showValleyBand =
    retYear != null && profile.roth_preference === "prefer_roth";

  return (
    <div className="relative mx-[30px] mb-[60px] mt-[90px]">
      <div className="relative h-[3px] rounded-full bg-[var(--g-hairline)]">
        {/* residency-clock shadow band [additive position from profile] */}
        {showResidencyBand && relYear != null ? (
          <div
            className="absolute h-[70px] rounded-[8px]"
            style={{
              top: "-34px",
              left: `${pct(minYear)}%`,
              width: `${Math.max(pct(relYear) - pct(minYear), 4)}%`,
              background:
                "repeating-linear-gradient(135deg, rgba(194,58,82,0.14) 0 6px, transparent 6px 12px)",
              borderRight: "2.5px solid var(--cliff)",
            }}
          >
            <span
              className="absolute left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-[9.5px] text-[var(--cliff)]"
              style={{ bottom: "-24px" }}
            >
              residency clock · [shadow additive]
            </span>
          </div>
        ) : null}

        {/* Roth valley shadow band [additive position from profile] */}
        {showValleyBand && retYear != null ? (
          <div
            className="absolute h-[70px] rounded-[8px]"
            style={{
              top: "-34px",
              left: `${Math.max(pct(retYear - 2), 0)}%`,
              width: `${Math.min(pct(retYear + 2) - pct(retYear - 2), 40)}%`,
              background:
                "repeating-linear-gradient(135deg, rgba(29,138,91,0.16) 0 6px, transparent 6px 12px)",
              outline: "1px dashed rgba(29,138,91,0.4)",
            }}
          >
            <span
              className="absolute left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-[9.5px] text-[var(--save)]"
              style={{ bottom: "-24px" }}
            >
              Roth valley · [shadow additive]
            </span>
          </div>
        ) : null}

        {/* event nodes */}
        {sorted.map((ev, i) => (
          <EventPin key={`${ev.year}-${i}`} ev={ev} pct={pct(ev.year)} />
        ))}
      </div>
    </div>
  );
}

function EventPin({ ev, pct: pctVal }: { ev: TlEvent; pct: number }) {
  const clampedPct = Math.min(Math.max(pctVal, 0), 97);
  return (
    <span
      className="absolute flex flex-col items-center"
      style={{ top: "-7px", left: `${clampedPct}%`, transform: "translateX(-50%)" }}
    >
      {/* card above */}
      <span className="absolute w-[160px] text-center" style={{ bottom: "26px" }}>
        <b className="block text-[12.5px] font-semibold">{ev.label}</b>
        {ev.sub ? (
          <span className="mt-[2px] block text-[10px] leading-[1.45] text-[var(--g-ink-3)]">
            {ev.sub}
          </span>
        ) : null}
      </span>
      {/* node dot */}
      <span
        className="z-[2] h-[15px] w-[15px] rounded-full border-[2.5px]"
        style={{
          background: "var(--g-surface-2)",
          borderColor: ev.major ? "var(--seal)" : "var(--g-ink-2)",
          boxShadow: ev.major ? "0 0 0 5px rgba(153,122,49,0.15)" : undefined,
        }}
      />
      {/* year below */}
      <span
        className="absolute font-mono text-[10px] text-[var(--g-ink-3)]"
        style={{ top: "22px" }}
      >
        {ev.year}
      </span>
    </span>
  );
}

/* ---- read view: the structured brief lines ---- */
function ReadBrief({
  objective,
  liquidity,
  relocation,
  charitable,
  charitableSubNote,
  retirement,
  risk,
  education,
  succession,
  notes,
  saved,
}: {
  objective: string | null;
  liquidity: string | null;
  relocation: string | null;
  charitable: string | null;
  charitableSubNote: string | null;
  retirement: string | null;
  risk: string | null;
  education: string | null;
  succession: string | null;
  notes: string | null;
  saved: boolean;
}) {
  return (
    <>
      {saved ? (
        <div className="mx-[18px] mb-1 mt-1 rounded-[8px] bg-[var(--save-soft)] px-3 py-2 font-mono text-[10.5px] text-[var(--save)]">
          ✓ Brief saved
        </div>
      ) : null}
      <BriefLine k="objective">
        {objective ?? (
          <span className="text-[var(--g-ink-3)]">Not captured — tap edit to add</span>
        )}
      </BriefLine>
      {liquidity ? <BriefLine k="liquidity event">{liquidity}</BriefLine> : null}
      {relocation ? <BriefLine k="relocation">{relocation}</BriefLine> : null}
      {charitable ? (
        <BriefLine k="charitable">
          {charitable}
          {charitableSubNote ? (
            <small className="mt-[2px] block text-[11px] text-[var(--g-ink-3)]">
              {charitableSubNote}
            </small>
          ) : null}
        </BriefLine>
      ) : null}
      {retirement ? (
        <BriefLine k={<Term k="roth-conversion">retirement</Term>}>{retirement}</BriefLine>
      ) : null}
      {risk ? <BriefLine k="risk · cash flow">{risk}</BriefLine> : null}
      {education ? <BriefLine k="education">{education}</BriefLine> : null}
      {succession ? <BriefLine k="succession">{succession}</BriefLine> : null}
      {notes ? (
        <BriefLine k="advisor notes">
          <span className="italic text-[var(--g-ink-2)]">{notes}</span>
        </BriefLine>
      ) : null}
    </>
  );
}

function BriefLine({
  k,
  children,
}: {
  k: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-3 border-t border-[var(--g-hairline-soft)] px-[18px] py-[12px] first:border-t-0">
      <span className="w-[132px] flex-none font-mono text-[9.5px] uppercase tracking-[0.1em] text-[var(--g-ink-3)]">
        {k}
      </span>
      <span className="text-[13.5px]">{children}</span>
    </div>
  );
}

/* ---- empty brief state ---- */
function EmptyBriefState({
  onEdit,
  clientName,
}: {
  onEdit: () => void;
  clientName?: string;
}) {
  return (
    <div className="px-[18px] py-[22px]">
      <div className="flex items-start gap-3">
        <Aavatar name="Strategist" agent="strategist" idle />
        <div>
          <p className="text-[13px] leading-relaxed text-[var(--g-ink-2)]">
            No brief yet{clientName ? ` for ${clientName}` : ""} — capture what they actually
            want, and the strategist will use it to tailor and prioritize every finding.
          </p>
          <p className="mt-1 text-[12px] text-[var(--g-ink-3)]">
            &ldquo;No goal, no speculation — the agent doesn&apos;t invent priorities.&rdquo;
          </p>
          <div className="mt-3">
            <MiniButton go onClick={onEdit}>
              Capture the brief
            </MiniButton>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---- edit form ---- */
function EditForm({
  draft,
  setProp,
}: {
  draft: Profile;
  setProp: <K extends keyof Profile>(k: K, v: Profile[K]) => void;
}) {
  const selectCls =
    "h-9 w-full rounded-[var(--radius-sm,6px)] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 text-[13px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]";

  return (
    <div className="px-[18px] pb-[18px] pt-2">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField label="Primary objective" className="sm:col-span-2">
          <select
            value={draft.primary_objective ?? "no_preference"}
            onChange={(e) => setProp("primary_objective", e.target.value)}
            className={selectCls}
          >
            {Object.entries(OBJECTIVE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Liquidity event">
          <select
            value={draft.liquidity_event ?? "none"}
            onChange={(e) => setProp("liquidity_event", e.target.value)}
            className={selectCls}
          >
            {Object.entries(LIQUIDITY_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        {draft.liquidity_event && draft.liquidity_event !== "none" ? (
          <>
            <FormField label="Event year">
              <input
                type="number"
                inputMode="numeric"
                value={draft.liquidity_event_year ?? ""}
                onChange={(e) =>
                  setProp(
                    "liquidity_event_year",
                    e.target.value ? parseInt(e.target.value, 10) : null,
                  )
                }
                placeholder="Year"
                className={selectCls}
              />
            </FormField>
            <FormField label="Est. proceeds / gain (dollars)">
              <input
                type="number"
                inputMode="numeric"
                value={
                  draft.liquidity_event_amount_cents != null
                    ? Math.round(draft.liquidity_event_amount_cents / 100)
                    : ""
                }
                onChange={(e) =>
                  setProp(
                    "liquidity_event_amount_cents",
                    e.target.value ? Math.round(parseFloat(e.target.value) * 100) : null,
                  )
                }
                placeholder="e.g. 5000000"
                className={selectCls}
              />
            </FormField>
          </>
        ) : null}

        <FormField label="Charitable intent">
          <select
            value={draft.charitable_intent ?? "none"}
            onChange={(e) => setProp("charitable_intent", e.target.value)}
            className={selectCls}
          >
            {Object.entries(CHARITABLE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        {draft.charitable_intent && draft.charitable_intent !== "none" ? (
          <FormField label="Annual giving (dollars)">
            <input
              type="number"
              inputMode="numeric"
              value={
                draft.annual_giving_cents != null
                  ? Math.round(draft.annual_giving_cents / 100)
                  : ""
              }
              onChange={(e) =>
                setProp(
                  "annual_giving_cents",
                  e.target.value ? Math.round(parseFloat(e.target.value) * 100) : null,
                )
              }
              placeholder="e.g. 25000"
              className={selectCls}
            />
          </FormField>
        ) : null}

        <FormField label="Target retirement year">
          <input
            type="number"
            inputMode="numeric"
            value={draft.retirement_target_year ?? ""}
            onChange={(e) =>
              setProp(
                "retirement_target_year",
                e.target.value ? parseInt(e.target.value, 10) : null,
              )
            }
            placeholder="Year"
            className={selectCls}
          />
        </FormField>

        <FormField label="Roth vs traditional preference">
          <select
            value={draft.roth_preference ?? "no_preference"}
            onChange={(e) => setProp("roth_preference", e.target.value)}
            className={selectCls}
          >
            {Object.entries(ROTH_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Planned relocation state">
          <input
            value={draft.planned_relocation_state ?? ""}
            onChange={(e) =>
              setProp(
                "planned_relocation_state",
                e.target.value.toUpperCase().slice(0, 2) || null,
              )
            }
            placeholder="e.g. TX"
            className={selectCls}
          />
        </FormField>

        <FormField label="Relocation year">
          <input
            type="number"
            inputMode="numeric"
            value={draft.relocation_year ?? ""}
            onChange={(e) =>
              setProp("relocation_year", e.target.value ? parseInt(e.target.value, 10) : null)
            }
            placeholder="Year"
            className={selectCls}
          />
        </FormField>

        <FormField label="Risk tolerance">
          <select
            value={draft.risk_tolerance ?? "moderate"}
            onChange={(e) => setProp("risk_tolerance", e.target.value)}
            className={selectCls}
          >
            {Object.entries(RISK_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Cash-flow sensitivity">
          <select
            value={draft.cash_flow_sensitivity ?? "medium"}
            onChange={(e) => setProp("cash_flow_sensitivity", e.target.value)}
            className={selectCls}
          >
            {Object.entries(CASHFLOW_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Business succession">
          <select
            value={draft.business_succession ?? "none"}
            onChange={(e) => setProp("business_succession", e.target.value)}
            className={selectCls}
          >
            {Object.entries(SUCCESSION_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FormField>

        <div className="flex items-center gap-2 text-[13px] text-[var(--g-ink-2)] sm:col-span-2">
          <input
            type="checkbox"
            checked={draft.education_funding ?? false}
            onChange={(e) => setProp("education_funding", e.target.checked)}
            className="h-4 w-4 rounded border-[var(--g-hairline)]"
          />
          Education funding for dependents (529 candidate)
        </div>

        <FormField label="Advisor notes" className="sm:col-span-2">
          <textarea
            value={draft.notes ?? ""}
            onChange={(e) => setProp("notes", e.target.value || null)}
            rows={3}
            placeholder="Anything else that should shape the plan…"
            className="w-full rounded-[var(--radius-sm,6px)] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 py-2 text-[13px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
          />
        </FormField>
      </div>
    </div>
  );
}

function FormField({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="mb-1.5 block font-mono text-[9.5px] uppercase tracking-[0.1em] text-[var(--g-ink-3)]">
        {label}
      </label>
      {children}
    </div>
  );
}

/* ---- goal → finding wire rows ---- */
function GoalFindingRow({
  goal,
  finding,
  disposition,
}: {
  goal: string;
  finding: string;
  disposition: string;
}) {
  const tone = ["signed", "accepted", "implementing"].includes(disposition) ? "save" : "neutral";
  return (
    <>
      <span className="justify-self-end">
        <Chip>{goal}</Chip>
      </span>
      <span className="text-center text-[12px] text-[var(--g-ink-3)]">→</span>
      <span className="justify-self-start">
        <Chip tone={tone as "save" | "neutral"}>{finding}</Chip>
      </span>
    </>
  );
}

/**
 * Derive a short "goal" label from the strategy name and category for the
 * BECAUSE map. Maps known strategy name patterns to the brief field they serve.
 */
function briefKeyForStrategy(name: string, category: string): string {
  const n = name.toLowerCase();
  if (n.includes("qsbs") || n.includes("1202")) return "liquidity event";
  if (
    n.includes("reloc") ||
    n.includes("texas") ||
    n.includes("state") ||
    n.includes("domicile") ||
    n.includes("residency")
  )
    return "relocation";
  if (n.includes("daf") || n.includes("charit") || n.includes("bunching"))
    return "charitable intent";
  if (n.includes("roth") || n.includes("conversion") || n.includes("retire"))
    return "retirement";
  if (n.includes("529") || n.includes("education")) return "education";
  if (n.includes("succession") || n.includes("business sale") || n.includes("exit"))
    return "succession";
  if (category) return category.replace(/_/g, " ");
  return "planning goal";
}
