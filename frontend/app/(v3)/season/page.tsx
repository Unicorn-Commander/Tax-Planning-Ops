"use client";

// Surface 11 — THE SEASON
// Year board: surge bands (spring review / Q4 crunch) + checkpoint nodes with
// funded counts. Surge queue: per-client paid-vs-required mini bar, safe-harbor
// basis, annualized flag, voucher + agent-drafted reminder (send is human).
// Pre-meeting cheat sheet: [additive]. Post-filing campaign: [additive].
//
// Live data:
//   GET /clients                       — list of clients
//   GET /clients/:id/overview          — overview.quarterly per client
//   (aggregated client-side)
//
// Additive (Honesty Protocol, spec §7-11):
//   agent-drafted reminders            — [additive] fixture labeled
//   pre-meeting cheat sheet            — [additive] fixture labeled
//   post-filing campaign               — [additive] fixture labeled
//
// Per-surface integration TODO: frontend/INTEGRATION-TODO.11.md

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Cavatar,
  MiniButton,
  Money,
  Term,
  Omnibar,
  hueForClient,
} from "@/components/kit";

/* ---- wire shapes -------------------------------------------------- */

interface ClientRow {
  id: string;
  display_name: string;
  filing_status_default: string;
  primary_state: string | null;
  status: string;
}

interface QuarterRow {
  quarter: number;
  due_date: string;
  required_payment_cents: number;
  payment_made_cents: number;
  unpaid_rollforward_cents: number;
  status: string;
  safe_harbor_basis?: string | null;
}

interface Overview {
  client: {
    id: string;
    display_name: string;
    filing_status_default: string;
    primary_state: string | null;
    status: string;
  };
  quarterly: QuarterRow[];
}

/* ---- helpers ------------------------------------------------------ */

/** Current quarter index by today's date (0-indexed, 1-4 as returned by API). */
function currentQuarter(): number {
  const m = new Date().getMonth() + 1; // 1–12
  if (m <= 4) return 1;
  if (m <= 6) return 2;
  if (m <= 9) return 3;
  return 4;
}

// IRS estimated-payment due dates are statutory constants (Apr 15 / Jun 15 /
// Sep 15 / Jan 15). The "· NOW" marker is NOT baked in here — it's derived from
// the actual current quarter in the checkpoints memo, so it moves with the date.
const Q_DATES: Record<number, { label: string; dateStr: string; position: string }> = {
  1: { label: "Q1", dateStr: "APR 15", position: "28%" },
  2: { label: "Q2", dateStr: "JUN 15", position: "45%" },
  3: { label: "Q3", dateStr: "SEP 15", position: "66%" },
  4: { label: "Q4", dateStr: "JAN 15", position: "92%" },
};

const BASIS_LABEL: Record<string, string> = {
  "90_current":           "90% current-year",
  "100_prior":            "100% prior-year",
  "110_prior_high_agi":   "110% prior (high AGI)",
};

function basisDisplay(basis: string | null | undefined, filing?: string): string {
  if (!basis) return "safe-harbor basis";
  const b = BASIS_LABEL[basis] ?? basis;
  if (filing?.toLowerCase() === "mfj") return `${b} · annualized off`;
  return b;
}

/** Compact money: $6.2k / $920 */
function fmtK(cents: number): string {
  const d = cents / 100;
  if (d >= 10_000) return `$${Math.round(d / 1000)}k`;
  if (d >= 1_000) return `$${(d / 1000).toFixed(1)}k`;
  return `$${Math.round(d).toLocaleString()}`;
}

/* ---- per-client quarterly data for the current checkpoint ---------- */

interface ClientQ {
  clientId: string;
  name: string;
  filing: string;
  hue: string;
  q: QuarterRow | undefined;
  basis: string | null;
  allQ: QuarterRow[];
  // derived
  paidCents: number;
  requiredCents: number;
  unpaidCents: number;
  paidFraction: number; // 0–1 width of the filled bar
  requiredFraction: number; // 0–1 where the required tick sits
  statusLabel: string;
  statusTone: "save" | "cost" | "neutral";
}

function deriveClientQ(
  id: string,
  name: string,
  filing: string,
  overview: Overview | undefined,
  qNum: number,
): ClientQ {
  const hue = hueForClient(id);
  const allQ = overview?.quarterly ?? [];
  const q = allQ.find((r) => r.quarter === qNum);

  // Cumulative paid vs required (all quarters through current)
  let cumPaid = 0;
  let cumRequired = 0;
  for (const r of allQ) {
    if (r.quarter > qNum) break;
    cumPaid += r.payment_made_cents;
    cumRequired += r.required_payment_cents;
  }

  const unpaidCents = q ? q.unpaid_rollforward_cents : Math.max(0, cumRequired - cumPaid);
  const basis = allQ[0]?.safe_harbor_basis ?? null;

  // Bar spans: paid = fraction of the required total; tick = required fraction relative to total possible
  const totalPossible = Math.max(cumRequired * 1.4, cumRequired + 10_000_00);
  const paidFraction = totalPossible > 0 ? Math.min(cumPaid / totalPossible, 1) : 0;
  const requiredFraction = totalPossible > 0 ? Math.min(cumRequired / totalPossible, 1) : 0;

  let statusLabel = "SAFE HARBOR MET";
  let statusTone: "save" | "cost" | "neutral" = "neutral";

  if (q) {
    if (q.status === "paid" || unpaidCents === 0) {
      statusLabel = q.payment_made_cents > 0 ? `PAID ${fmtK(cumPaid)} ✓` : "W/H COVERS ✓";
      statusTone = "save";
    } else if (unpaidCents > 0) {
      statusLabel = `DUE ${fmtK(unpaidCents)}`;
      statusTone = "cost";
    }
  } else if (!overview) {
    statusLabel = "loading…";
    statusTone = "neutral";
  }

  return {
    clientId: id,
    name,
    filing,
    hue,
    q,
    basis,
    allQ,
    paidCents: cumPaid,
    requiredCents: cumRequired,
    unpaidCents,
    paidFraction,
    requiredFraction,
    statusLabel,
    statusTone,
  };
}

/* ---- checkpoint state for the year board -------------------------- */

interface Checkpoint {
  quarter: number;
  label: string;
  dateStr: string;
  position: string; // CSS `left` value for the y-track
  fundedCount: number;
  totalCount: number;
  open: boolean;
}

/* ================================================================== */
export default function SeasonPage() {
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [overviews, setOverviews] = useState<Record<string, Overview>>({});
  const overviewsRef = useRef<Record<string, Overview>>({});

  const qNum = useMemo(() => currentQuarter(), []);

  /* ---- initial fetch: client list ---- */
  useEffect(() => {
    api.get("/clients").then((r) => setClients(r.data)).catch(() => setClients([]));
  }, []);

  /* ---- fan-out overview per client ---- */
  useEffect(() => {
    if (!clients) return;
    for (const c of clients) {
      if (overviewsRef.current[c.id]) continue;
      api
        .get(`/clients/${c.id}/overview`)
        .then((r: { data: Overview }) => {
          overviewsRef.current = { ...overviewsRef.current, [c.id]: r.data };
          setOverviews((prev) => ({ ...prev, [c.id]: r.data }));
        })
        .catch(() => {/* overview unavailable; row renders as loading */});
    }
  }, [clients]);

  /* ---- per-client Q data ---- */
  const clientQList: ClientQ[] = useMemo(() => {
    if (!clients) return [];
    return clients.map((c) =>
      deriveClientQ(c.id, c.display_name, c.filing_status_default, overviews[c.id], qNum),
    );
  }, [clients, overviews, qNum]);

  /* ---- unpaid-first ordering (due clients on top) ---- */
  const sortedQ = useMemo(
    () =>
      [...clientQList].sort((a, b) => {
        const aOpen = a.unpaidCents > 0 ? 1 : 0;
        const bOpen = b.unpaidCents > 0 ? 1 : 0;
        if (aOpen !== bOpen) return bOpen - aOpen;
        return b.unpaidCents - a.unpaidCents;
      }),
    [clientQList],
  );

  /* ---- season totals ---- */
  const totals = useMemo(() => {
    let required = 0;
    let funded = 0;
    let open = 0;
    let openCount = 0;
    for (const cq of clientQList) {
      required += cq.requiredCents;
      funded += cq.paidCents;
      if (cq.unpaidCents > 0) {
        open += cq.unpaidCents;
        openCount++;
      }
    }
    return { required, funded, open, openCount };
  }, [clientQList]);

  /* ---- checkpoint funded counts for the year board ---- */
  const checkpoints: Checkpoint[] = useMemo(() => {
    const total = clientQList.length;
    return [1, 2, 3, 4].map((q) => {
      const cfg = Q_DATES[q];
      const funded = clientQList.filter((cq) => {
        const qr = cq.allQ.find((r) => r.quarter === q);
        if (!qr) return false;
        return qr.status === "paid" || qr.unpaid_rollforward_cents === 0;
      }).length;
      return {
        quarter: q,
        label: cfg.label,
        dateStr: q === qNum ? `${cfg.dateStr} · NOW` : cfg.dateStr,
        position: cfg.position,
        fundedCount: funded,
        totalCount: total,
        open: q === qNum,
      };
    });
  }, [clientQList, qNum]);

  const loading = clients === null;
  const totalClients = clients?.length ?? 0;
  const openCount = sortedQ.filter((cq) => cq.unpaidCents > 0).length;

  /* ================================================================ */
  return (
    <div className="wrap py-7 pb-16">

      {/* ---- page head ---- */}
      <section className="rise flex flex-wrap items-center gap-[14px]">
        <div>
          <h1 className="text-[30px] font-extrabold leading-none tracking-[-0.02em]">The Season</h1>
          <Annotation className="mt-1 block">
            tax planning is calendar-driven — the year is the board
          </Annotation>
        </div>
        {openCount > 0 ? (
          <Chip tone="cost" className="ml-auto">
            Q{qNum} federal estimates · {openCount} open
          </Chip>
        ) : (
          <Chip className="ml-auto">
            Q{qNum} · {loading ? "loading…" : `${totalClients} clients tracked`}
          </Chip>
        )}
      </section>

      {/* ================================================================ YEAR BOARD */}
      <Panel className="rise d1 relative mt-6 px-7 pb-14 pt-5">
        <PanelHead className="!border-0 !pb-2">
          <MicroLabel>Planning year 2026 · surges and checkpoints</MicroLabel>
          <span className="chip ml-auto">same agenda every surge — that&apos;s how one advisor serves a whole book</span>
        </PanelHead>

        {/* The y-track timeline */}
        <div
          className="relative mx-4 mt-[74px] h-[3px] rounded-full bg-[var(--g-hairline)]"
          role="img"
          aria-label="Planning year timeline with surge bands and quarterly checkpoints"
        >
          {/* Spring review surge band */}
          <div
            className="surge spring absolute rounded-[9px]"
            style={{
              left: "24%",
              width: "14%",
              top: "-30px",
              height: "62px",
              background: "rgba(29,138,91,0.10)",
              outline: "1px solid rgba(29,138,91,0.25)",
            }}
            aria-hidden
          >
            <span
              className="absolute bottom-[-24px] left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-[9.5px] text-[var(--g-ink-3)]"
            >
              SPRING REVIEW ✓
            </span>
          </div>

          {/* Q4 crunch surge band (upcoming — dashed) */}
          <div
            className="absolute rounded-[9px]"
            style={{
              left: "74%",
              width: "16%",
              top: "-30px",
              height: "62px",
              background: "rgba(91,134,168,0.10)",
              outline: "1px dashed rgba(91,134,168,0.30)",
            }}
            aria-hidden
          >
            <span
              className="absolute bottom-[-24px] left-1/2 -translate-x-1/2 whitespace-nowrap font-mono text-[9.5px] text-[var(--g-ink-3)]"
            >
              Q4 CRUNCH · coming
            </span>
          </div>

          {/* Filing handoff node */}
          <CheckpointNode
            label="Filing handoff"
            sub="CPA letters sent ✓"
            dateStr="FEB–APR"
            position="8%"
            state="done"
          />

          {/* Q1–Q4 checkpoint nodes */}
          {checkpoints.map((cp) => {
            const state = cp.open
              ? (cp.fundedCount < cp.totalCount ? "due" : "done")
              : cp.quarter < qNum
              ? "done"
              : "todo";
            const sub =
              cp.totalCount === 0
                ? "no clients loaded"
                : cp.open
                ? `${cp.fundedCount}/${cp.totalCount} funded${cp.fundedCount < cp.totalCount ? ` · ${fmtK(totals.open)} open` : " ✓"}`
                : cp.quarter < qNum
                ? `${cp.fundedCount}/${cp.totalCount} funded ✓`
                : cp.quarter === 3
                ? "re-projects on July books"
                : "final · Jan 15 '27";
            return (
              <CheckpointNode
                key={cp.quarter}
                label={cp.label}
                sub={sub}
                dateStr={cp.dateStr}
                position={cp.position}
                state={state}
              />
            );
          })}
        </div>
      </Panel>

      {/* ================================================================ MAIN GRID */}
      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1.62fr_1fr]">

        {/* ==== LEFT COLUMN ==== */}
        <div className="flex flex-col gap-[22px]">

          {/* ---- surge queue ---- */}
          <Panel className="rise d2">
            <PanelHead>
              <MicroLabel>Q{qNum} board · cumulative paid vs required, per client</MicroLabel>
              <Annotation className="!text-[13px]">
                a dip below the step line = a <Term k="safe-harbor">2210</Term> penalty, priced
              </Annotation>
              {/* TODO(integration: POST /agents/season/draft-reminders) — agent-drafted reminders */}
              {openCount > 0 ? (
                <button
                  type="button"
                  className="chip agent ml-auto"
                  title="[additive] Agent-drafted reminder emails (spec §7-11)"
                >
                  draft reminders for the unpaid · {openCount}
                </button>
              ) : null}
            </PanelHead>

            {loading ? (
              <div className="space-y-px">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="skeleton mx-4 my-3 h-[52px] rounded-[8px]" />
                ))}
              </div>
            ) : sortedQ.length === 0 ? (
              <div className="px-6 py-10 text-center">
                <p className="text-[14px] font-semibold text-[var(--g-ink)]">No clients in the book yet</p>
                <p className="mt-1 text-[13px] text-[var(--g-ink-3)]">
                  Add a client and compute quarterly estimates to populate the season board.
                </p>
                <div className="mt-4 flex justify-center">
                  <Link href="/c/new/return" className="btn btn-ink text-[13px]">
                    Drop a 1040
                  </Link>
                </div>
              </div>
            ) : (
              <div>
                {sortedQ.map((cq) => (
                  <SurgeRow key={cq.clientId} cq={cq} />
                ))}
              </div>
            )}
          </Panel>

          {/* ---- post-filing campaign card: [additive] ---- */}
          <Panel className="rise d3 px-5 py-[18px]">
            {/* TODO(integration: POST /agents/season/post-filing-campaign) — bulk drop + re-rank + outreach drafts */}
            <div
              className="mb-1 font-mono text-[10.5px] uppercase tracking-[0.08em]"
              style={{ color: "var(--agent)" }}
            >
              Campaign · post-filing review <span className="chip ml-2 !text-[9px]">[additive] fixture</span>
            </div>
            <p className="my-3 text-[13px] leading-relaxed text-[var(--g-ink-2)]">
              <b>The spring loop that fills the year:</b> drop the book&apos;s just-filed returns in bulk →
              the clerk verifies each against a full recompute → the bookrunner re-ranks → outreach
              drafts carry each client&apos;s headline number. {totalClients > 0 ? `${totalClients} of ${totalClients} collected this spring` : "Ready when returns are in"}.
            </p>
            <div className="flex flex-wrap gap-2">
              <Link href="/c/new/return" className="mini-btn go">
                Drop returns (bulk)
              </Link>
              <Link href="/book" className="mini-btn">
                Ranked results →
              </Link>
              <span className="chip ml-auto">prospect upload links: [additive]</span>
            </div>
          </Panel>
        </div>

        {/* ==== RIGHT COLUMN ==== */}
        <div className="flex flex-col gap-[22px]">

          {/* ---- cheat sheet: [additive] ---- */}
          <Panel className="rise d3">
            <PanelHead>
              <MicroLabel>Surge prep · the cheat sheet</MicroLabel>
              <span className="chip agent ml-auto">[additive] auto-drafted per meeting</span>
            </PanelHead>
            {/* TODO(integration: POST /agents/season/cheat-sheet) — compose from overview + analysis + plan */}
            <div className="px-[18px] py-4 text-[12.5px] leading-[1.7] text-[var(--g-ink-2)]">
              <div
                className="mb-3 rounded-[8px] border border-[var(--g-hairline)] px-3 py-2 font-mono text-[10px] text-[var(--g-ink-3)]"
              >
                [additive] The cheat sheet compiles from each client&apos;s overview + analysis + plan +
                season state — agent work product, advisor sends. Wire via
                POST /agents/season/cheat-sheet (spec §7-11).
              </div>
              <b className="block text-[13.5px] text-[var(--g-ink)]">
                {sortedQ[0]?.name ?? "First client"} — next surge
              </b>
              {sortedQ[0] ? (
                <>
                  <span className="mt-1 block">
                    · open:{" "}
                    {sortedQ[0].unpaidCents > 0 ? (
                      <b className="fig text-[var(--cost)]">
                        {centsToUSD(sortedQ[0].unpaidCents)} Q{qNum}
                      </b>
                    ) : (
                      <b className="fig text-[var(--save)]">funded ✓</b>
                    )}
                  </span>
                  <span className="mt-0.5 block text-[var(--g-ink-3)]">
                    · basis: {basisDisplay(sortedQ[0].basis, sortedQ[0].filing)}
                  </span>
                </>
              ) : null}
            </div>
            <div className="flex gap-2 px-[18px] pb-4">
              <MiniButton>All upcoming briefs</MiniButton>
              <Link href="/c/new" className="mini-btn go">Open present mode ▸</Link>
            </div>
          </Panel>

          {/* ---- season totals ---- */}
          <Panel className="rise d4">
            <PanelHead>
              <MicroLabel>Season totals · Q{qNum} book</MicroLabel>
            </PanelHead>
            <div className="grid grid-cols-2">
              <TotalCell
                value={loading ? "—" : <Money cents={totals.required} />}
                label={`Q${qNum} REQUIRED · BOOK`}
                border="right"
              />
              <TotalCell
                value={loading ? "—" : <Money cents={totals.funded} tone="save" />}
                label="FUNDED ✓"
              />
              <TotalCell
                value={loading ? "—" : <Money cents={totals.open} tone={totals.open > 0 ? "cost" : undefined} />}
                label={`OPEN · ${totals.openCount} CLIENT${totals.openCount !== 1 ? "S" : ""}`}
                border="right top"
              />
              <TotalCell
                value={
                  // TODO(integration: GET /quarterly/penalty-exposure) — 2210 penalty check per client
                  <span className="money fig text-[var(--g-ink-3)]">—</span>
                }
                label="PENALTY EXPOSURE [additive]"
                border="top"
                note="2210 safe-harbor check — additive (spec §9)"
              />
            </div>
          </Panel>

          {/* ---- spec note / provenance footer ---- */}
          <div
            className="rise d5 rounded-[10px] border border-[var(--g-hairline)] px-4 py-3 font-mono text-[10px] text-[var(--g-ink-3)]"
          >
            SPEC · board = quarterly engine per client (<Term k="safe-harbor">safe-harbor basis</Term> shown;
            2210-AI when income is lumpy). Mini-bars: paid vs the cumulative-required tick. Reminder
            drafts are agent work products — advisor sends. Cheat sheets compile from overview +
            analysis + plan + season state.
          </div>
        </div>
      </div>

      {/* ---- omnibar (three-doors contract) ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about the season — or ⌘K for actions…" />
      </div>
    </div>
  );
}

/* ================================================================== CHECKPOINT NODE */

function CheckpointNode({
  label,
  sub,
  dateStr,
  position,
  state,
}: {
  label: string;
  sub: string;
  dateStr: string;
  position: string;
  state: "done" | "due" | "todo";
}) {
  const dotClass =
    state === "done"
      ? "bg-[var(--save)] border-[var(--save)]"
      : state === "due"
      ? "bg-[var(--cost)] border-[var(--cost)]"
      : "bg-[var(--g-surface-2)] border-[var(--g-ink-3)]";
  const shadow =
    state === "due"
      ? "0 0 0 6px rgba(170,106,28,0.16)"
      : undefined;
  return (
    <span
      className="absolute flex -translate-x-1/2 flex-col items-center"
      style={{ top: "-7px", left: position }}
      aria-label={`${label} — ${sub}`}
    >
      {/* label card above */}
      <span className="absolute bottom-[24px] w-[130px] text-center">
        <b className="block text-[12px]">{label}</b>
        <span className="block text-[9.5px] text-[var(--g-ink-3)]">{sub}</span>
      </span>
      {/* dot */}
      <span
        className={`relative z-10 h-[14px] w-[14px] rounded-full border-[2.5px] ${dotClass}`}
        style={shadow ? { boxShadow: shadow } : undefined}
      />
      {/* date below */}
      <span className="absolute top-[20px] whitespace-nowrap font-mono text-[9.5px] text-[var(--g-ink-3)]">
        {dateStr}
      </span>
    </span>
  );
}

/* ================================================================== SURGE ROW */

function SurgeRow({ cq }: { cq: ClientQ }) {
  const isOpen = cq.unpaidCents > 0;
  const opacity = isOpen ? undefined : "0.65";

  return (
    <div
      className="grid items-center gap-[14px] border-t border-[var(--g-hairline-soft)] px-[18px] py-3 first:border-t-0"
      style={{
        gridTemplateColumns: "auto 1.2fr 120px 140px 1fr auto",
        opacity,
      }}
      aria-label={`${cq.name}: ${cq.statusLabel}`}
    >
      {/* Avatar */}
      <Cavatar name={cq.name} hue={cq.hue} className="!h-[32px] !w-[32px] !text-[11px]" />

      {/* Name + basis */}
      <div>
        <b className="block text-[13.5px]">{cq.name}</b>
        <span className="font-mono text-[10px] text-[var(--g-ink-3)]">
          {basisDisplay(cq.basis, cq.filing)}
        </span>
      </div>

      {/* Status */}
      <span
        className="font-mono text-[10.5px]"
        style={{
          color:
            cq.statusTone === "save"
              ? "var(--save)"
              : cq.statusTone === "cost"
              ? "var(--cost)"
              : "var(--g-ink-3)",
        }}
      >
        {cq.statusLabel}
      </span>

      {/* Mini paid-vs-required bar */}
      <MiniStepBar paidFraction={cq.paidFraction} requiredFraction={cq.requiredFraction} />

      {/* Context note — placeholder for additive per-client note */}
      <span className="text-[11.5px] text-[var(--g-ink-3)]">
        {isOpen
          ? "voucher staged · EFTPS link in draft email"
          : cq.statusLabel.includes("W/H")
          ? "withholding covers — monitor for vest/bonus events"
          : "funded — continue monitoring"}
      </span>

      {/* Action */}
      {isOpen ? (
        // TODO(integration: POST /agents/season/draft-reminders?client_id) — send voucher + note
        <button
          type="button"
          className="mini-btn go"
          title="[additive] Sends agent-drafted voucher reminder (spec §7-11)"
          onClick={() => {
            /* additive: POST /agents/season/draft-reminders */
          }}
        >
          Send voucher + note
        </button>
      ) : (
        <span />
      )}
    </div>
  );
}

/* ================================================================== MINI STEP BAR */

/**
 * Horizontal mini bar: green fill = paid fraction, hairline tick = required fraction.
 * Pure CSS, no SVG. The tick marks "safe harbor" (the step the bar must clear).
 */
function MiniStepBar({
  paidFraction,
  requiredFraction,
}: {
  paidFraction: number;
  requiredFraction: number;
}) {
  return (
    <div
      className="relative h-[6px] overflow-visible rounded-full"
      style={{ background: "rgba(31,28,23,0.08)" }}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(paidFraction * 100)}
      aria-label="Paid vs required"
    >
      {/* paid fill */}
      <span
        className="absolute inset-y-0 left-0 rounded-full"
        style={{
          width: `${(paidFraction * 100).toFixed(1)}%`,
          background: "var(--save)",
        }}
      />
      {/* required tick */}
      <span
        className="absolute top-[-2px] bottom-[-2px] w-[1.5px] rounded-full"
        style={{
          left: `${(requiredFraction * 100).toFixed(1)}%`,
          background: "rgba(31,28,23,0.45)",
        }}
        aria-hidden
      />
    </div>
  );
}

/* ================================================================== TOTAL CELL */

function TotalCell({
  value,
  label,
  border,
  note,
}: {
  value: ReactNode;
  label: string;
  border?: string;
  note?: string;
}) {
  const classes = [
    "px-[18px] py-[14px]",
    border?.includes("right") ? "border-r border-[var(--g-hairline-soft)]" : "",
    border?.includes("top") ? "border-t border-[var(--g-hairline-soft)]" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes}>
      <div className="text-[20px] font-bold leading-none tracking-[-0.02em]">{value}</div>
      <div className="mt-1 font-mono text-[9px] uppercase tracking-[0.08em] text-[var(--g-ink-3)]">
        {label}
      </div>
      {note ? (
        <div className="mt-0.5 font-mono text-[9px] text-[var(--g-ink-3)]">{note}</div>
      ) : null}
    </div>
  );
}
