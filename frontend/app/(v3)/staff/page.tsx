"use client";

// Surface 10 — THE STAFF
// Agents as staff: avatar + presence, model line, standing orders (§, editable),
// the autonomy dial, stats strip, recent decisions including declines/escalations.
// Three doors: Console / MCP / API + live traffic feed with verdicts.
// House rules HR-01…05. Audit chain verify chip.
//
// Live data wired:
//   GET /lifecycle/audit/verify  — { valid: boolean }
//
// Additive (spec §7-10, Honesty Protocol) — CLEARLY LABELED FIXTURES:
//   Agent registry / status    — no backend endpoint yet; rendered from FIXTURE_AGENTS
//   MCP traffic feed           — no journal read API yet; rendered from FIXTURE_TRAFFIC
//   Door usage counts          — no real counters yet; rendered from FIXTURE_DOORS
//
// Per-surface integration TODO: frontend/INTEGRATION-TODO.10.md

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import api from "@/lib/api";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Aavatar,
  MiniButton,
  Omnibar,
  type AgentKey,
  AGENT_HUES,
} from "@/components/kit";

/* ------------------------------------------------------------------ */
/* LIVE wire shape                                                       */
/* ------------------------------------------------------------------ */

interface AuditVerifyResponse {
  valid: boolean;
}

/* ------------------------------------------------------------------ */
/* FIXTURE DATA — clearly labelled; replace when additive endpoints land */
/* ------------------------------------------------------------------ */

// TODO(integration: GET /agents/registry) — agent registry + status (spec §9.6)
interface DialTier {
  label: string;
  actionClass?: string;
  active: boolean;
}
interface AgentDecision {
  text: string;
  time: string;
  tone?: "decline" | "escalate" | "act";
}
interface AgentStat {
  value: string;
  label: string;
}
interface AgentFixture {
  key: AgentKey;
  name: string;
  modelLine: string;
  standingOrders: string;
  dial: DialTier[];
  stats: AgentStat[];
  decisions: AgentDecision[];
  idle?: boolean;
}

const FIXTURE_AGENTS: AgentFixture[] = [
  {
    key: "strategist",
    name: "The Strategist",
    modelLine: "qwen3.6-35b · suite gateway · engines as tools · per-client memory",
    standingOrders:
      "Figures from engines only — never compose a number. Tie every finding to a stated goal. Pause and ask on any unverified input. Draft in the firm’s voice; the advisor signs.",
    dial: [
      { label: "observe", active: false },
      { label: "propose · memos", active: true, actionClass: "memos" },
      { label: "act w/ review", active: false },
      { label: "act in bounds", active: false },
    ],
    stats: [
      { value: "34", label: "runs / wk" },
      { value: "94%", label: "findings accepted" },
      { value: "41s", label: "avg run" },
      { value: "14", label: "engine calls / run" },
    ],
    decisions: [
      { text: "declined to size Webb’s conversion — basis unverified → asked instead", time: "17:18", tone: "decline" },
      { text: "escalated: Nair RSU double-count suspicion in OCR vs W-2", time: "16:55", tone: "escalate" },
    ],
  },
  {
    key: "clerk",
    name: "The Intake Clerk",
    modelLine: "qwen3.6-vision (P40) → structurer · 200dpi 2-step · bbox provenance",
    standingOrders:
      "Read, never infer. Confidence routes review — sort lowest first. A field under 95% always gets a human eye. Recompute must match the return before baseline unlocks.",
    dial: [
      { label: "observe", active: false },
      { label: "propose", active: false },
      { label: "act w/ review · fields", active: true, actionClass: "fields" },
      { label: "act in bounds", active: false },
    ],
    stats: [
      { value: "11", label: "returns / wk" },
      { value: "99.2%", label: "field accuracy" },
      { value: "38s", label: "avg import" },
      { value: "1", label: "awaiting your eye" },
    ],
    decisions: [
      { text: "flagged Hartman 5b at 88% — handwriting over print, region attached", time: "16:12", tone: "escalate" },
    ],
    idle: true,
  },
  {
    key: "bookrunner",
    name: "The Bookrunner",
    modelLine: "scan-book · ranks by FULL recompute · watches constants drift",
    standingOrders:
      "Re-rank nightly and after any law/constants change. Surface movers with the reason. Never rank by tax owed — rank by what we can still recover.",
    dial: [
      { label: "observe", active: false },
      { label: "propose", active: false },
      { label: "act w/ review", active: false },
      { label: "act in bounds · scans", active: true, actionClass: "scans" },
    ],
    stats: [
      { value: "6/6", label: "book ranked" },
      { value: "2", label: "movers today" },
      { value: "$1.88M", label: "identified open" },
      { value: "nightly", label: "cadence" },
    ],
    decisions: [
      { text: "re-ranked after 2026 IRMAA update — Cho +$2,140, reason attached", time: "17:31", tone: "act" },
    ],
    idle: true,
  },
  {
    key: "liaison",
    name: "The AO Liaison",
    modelLine: "Accounting-Ops P&L · KC mint → Brigade RFC-8693 → AO · read-only",
    standingOrders:
      "Pull on monthly close + on demand. Propose entity updates, never write them. Stamp every figure with its as-of date. HIPAA workspaces are off-limits by policy.",
    dial: [
      { label: "observe", active: false },
      { label: "propose · applies", active: true, actionClass: "applies" },
      { label: "act w/ review", active: false },
      { label: "act in bounds", active: false },
    ],
    stats: [
      { value: "2", label: "entities linked" },
      { value: "17:02", label: "last pull" },
      { value: "300s", label: "token ttl" },
      { value: "viewer", label: "AO role cap" },
    ],
    decisions: [
      { text: "pulled Alvarez Studio YTD $31,440 — 12% under plan pace → proposed re-projection", time: "17:02", tone: "act" },
    ],
    idle: true,
  },
];

// TODO(integration: GET /lifecycle/journal?tail=20) — real MCP traffic feed (spec §9.5)
interface TrafficRow {
  caller: string;
  door: string;
  path: string;
  verdict: string;
  ok: boolean;
  time: string;
}
const FIXTURE_TRAFFIC: TrafficRow[] = [
  { caller: "strategist", door: "MCP", path: "GET …/tax-years/8f21/strategist", verdict: "200 · memo drafted", ok: true, time: "17:18:09" },
  { caller: "tax-planning-ops → AO", door: "API", path: "GET /reports/pl?ws=7775…", verdict: "200 · net_income", ok: true, time: "17:02:44" },
  { caller: "d.reyes", door: "console", path: "POST /plans/…/finalize", verdict: "sealed · hash stamped", ok: true, time: "16:48:02" },
  { caller: "unknown client", door: "API", path: "GET /clients (no workspace)", verdict: "403 · RLS", ok: false, time: "15:11:37" },
];

// TODO(integration: GET /agents/door-stats) — real door usage counts (spec §9.6)
interface DoorFixture {
  id: string;
  label: ReactNode;
  value: ReactNode;
  detail: string;
  hot?: boolean;
}

/* ------------------------------------------------------------------ */
/* HOUSE RULES — static design copy (not data)                          */
/* ------------------------------------------------------------------ */

const HOUSE_RULES = [
  { no: "HR-01", title: "Engines compute, AI narrates", body: "The model cannot invent a figure. Every dollar resolves to an engine trace." },
  { no: "HR-02", title: "Propose, never publish", body: "Nothing reaches a client without an advisor’s signature. Gold = signed." },
  { no: "HR-03", title: "Pause and ask", body: "Ambiguity becomes a priced question, never a silent assumption." },
  { no: "HR-04", title: "Sign the work", body: "Every artifact embeds actor, engines, inputs, hashes — exports included." },
  { no: "HR-05", title: "Autonomy is per action", body: "Four tiers, set by you, enforced at the gate, changes logged." },
];

/* ------------------------------------------------------------------ */
/* PAGE                                                                  */
/* ------------------------------------------------------------------ */

export default function StaffPage() {
  const [auditValid, setAuditValid] = useState<boolean | null>(null);
  const [auditLoading, setAuditLoading] = useState(true);

  // LIVE: GET /lifecycle/audit/verify
  useEffect(() => {
    api
      .get<AuditVerifyResponse>("/lifecycle/audit/verify")
      .then((r) => setAuditValid(r.data.valid))
      .catch(() => setAuditValid(null))
      .finally(() => setAuditLoading(false));
  }, []);

  // Door fixture values built here so JSX is available
  const FIXTURE_DOORS: DoorFixture[] = [
    {
      id: "console",
      label: "Console — you",
      value: <span className="text-[22px] font-[750]">4</span>,
      detail: "awaiting sign-off · every client-facing artifact passes here",
    },
    {
      id: "mcp",
      label: "MCP — agents & Claude",
      value: (
        <span className="text-[22px] font-[750]">
          182
          <span className="text-[12px] text-[var(--g-ink-3)]"> calls today</span>
        </span>
      ),
      detail: "21 tools · top: scan_book, strategist, analysis · Brigade-discoverable",
      hot: true,
    },
    {
      id: "api",
      label: "API — services",
      value: <span className="text-[22px] font-[750]">37</span>,
      detail: "AO federation reads · PDF renders · service tokens, scope-capped",
    },
  ];

  const auditChip = auditLoading ? (
    <span className="chip text-[var(--g-ink-3)]">audit chain … verifying</span>
  ) : auditValid === true ? (
    <Chip tone="save">audit chain ✓ verified</Chip>
  ) : auditValid === false ? (
    <Chip tone="cliff">audit chain ✗ invalid</Chip>
  ) : (
    <Chip tone="neutral">audit chain — unavailable</Chip>
  );

  return (
    <div className="wrap py-7 pb-16">

      {/* ---- page head ---- */}
      <section className="rise flex flex-wrap items-baseline gap-[14px]">
        <h1 className="m-0 text-[30px] font-[750] leading-none tracking-[-0.02em]">The Staff</h1>
        <Annotation>staff, not features — named, scoped, accountable, and on the record</Annotation>
        {/* FIXTURE — additive; real figures come from agent registry (spec §9.6) */}
        {/* TODO(integration: GET /agents/registry/stats) — on-duty count, weekly actions, approval rate, inference cost */}
        <div className="ml-auto flex gap-[20px] text-[12.5px] text-[var(--g-ink-3)]">
          <span>on duty <b className="text-[var(--g-ink)]">4</b></span>
          <span>actions this week <b className="text-[var(--g-ink)]">312</b></span>
          <span>approved <b className="text-[var(--g-ink)]">96%</b></span>
          <span>inference this month <b className="fig text-[var(--g-ink)]">$0.00 — local</b></span>
        </div>
      </section>

      {/* ---- fixture banner (Honesty Protocol) ---- */}
      <div className="rise d1 mt-3 rounded-[10px] border border-[color-mix(in_srgb,var(--cost)_35%,transparent)] bg-[color-mix(in_srgb,var(--cost)_5%,transparent)] px-4 py-2.5 font-mono text-[10.5px] text-[var(--cost)]">
        [fixture] Agent registry, traffic feed, and door stats are rendered from static fixture data.
        {" "}The audit chain chip above is wired live (GET /lifecycle/audit/verify).
        {" "}Replace fixtures when GET /agents/registry + GET /lifecycle/journal land (spec §9.5–9.6).
      </div>

      {/* ---- agent crew (2-column grid) ---- */}
      <div className="rise d2 mt-5 grid grid-cols-1 gap-[22px] md:grid-cols-2" style={{ alignItems: "start" }}>
        {FIXTURE_AGENTS.map((agent, i) => (
          <AgentCard key={agent.key} agent={agent} delay={i + 1} />
        ))}
      </div>

      {/* ---- the three doors ---- */}
      <Panel className="rise d5 mt-[22px]">
        <PanelHead>
          <MicroLabel>The doors · humans, agents, and services enter the same engine through the same gate</MicroLabel>
          <span className="ml-auto">{auditChip}</span>
        </PanelHead>
        {/* door cells */}
        <div className="grid grid-cols-3">
          {FIXTURE_DOORS.map((door) => (
            <div
              key={door.id}
              className={`border-l border-[var(--g-hairline-soft)] px-5 py-4 first:border-l-0 ${door.hot ? "bg-[rgba(17,130,123,0.05)]" : ""}`}
            >
              <b className="block text-[14px]">{door.label}</b>
              <div className="mt-2">{door.value}</div>
              <div className="mt-[3px] text-[11px] text-[var(--g-ink-3)]">{door.detail}</div>
            </div>
          ))}
        </div>
        {/* traffic feed — FIXTURE */}
        {/* TODO(integration: GET /lifecycle/journal?tail=20) — real MCP traffic feed */}
        <div className="font-mono text-[10.5px]">
          {FIXTURE_TRAFFIC.map((row, i) => (
            <div
              key={i}
              className="flex flex-wrap gap-[14px] border-t border-[var(--g-hairline-soft)] px-5 py-[7px] text-[var(--g-ink-3)]"
            >
              <b className="text-[var(--g-ink-2)] font-[500]">{row.caller}</b>
              <span>{row.door}</span>
              <span className="hidden sm:inline">{row.path}</span>
              <span className={row.ok ? "text-[var(--save)]" : "text-[var(--cliff)]"}>{row.verdict}</span>
              <span className="ml-auto">{row.time}</span>
            </div>
          ))}
        </div>
      </Panel>

      {/* ---- house rules ---- */}
      <div className="rise d6 mt-[22px] grid grid-cols-1 gap-[14px] sm:grid-cols-3 lg:grid-cols-5">
        {HOUSE_RULES.map((rule) => (
          <div
            key={rule.no}
            className="rounded-[12px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-[16px] py-[14px]"
          >
            <span className="font-mono text-[9.5px] tracking-[0.1em] text-[var(--seal)]">{rule.no}</span>
            <b className="mt-[6px] block text-[12.5px]">{rule.title}</b>
            <p className="m-0 mt-[5px] text-[11px] leading-[1.5] text-[var(--g-ink-3)]">{rule.body}</p>
          </div>
        ))}
      </div>

      {/* ---- ops recommendations (FIXTURE) ---- */}
      {/* TODO(integration: GET /agents/recommendations) — surface ops recommendations */}
      <Panel className="rise d6 mt-[22px] px-5 py-4">
        <MicroLabel className="text-[var(--g-ink-3)]">ops recommendations [fixture]</MicroLabel>
        <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
          2 clients are missing goals briefs — analyses will be weaker for them.{" "}
          <Link href="/book" className="text-[var(--agent)] underline underline-offset-2">
            Request intake →
          </Link>
        </p>
      </Panel>

      {/* ---- omnibar (the three-doors contract) ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the staff a question — or ⌘K for actions…" />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* AGENT CARD                                                            */
/* ------------------------------------------------------------------ */

function AgentCard({ agent, delay }: { agent: AgentFixture; delay: number }) {
  const ahue = AGENT_HUES[agent.key];

  return (
    <section
      className={`panel agentcard rise d${delay}`}
    >
      {/* top: avatar + identity + talk button */}
      <div className="flex gap-[14px] px-[20px] pb-[12px] pt-[18px]">
        <Aavatar
          name={agent.name}
          hue={ahue}
          idle={agent.idle}
          className="!h-[46px] !w-[46px] !text-[17px]"
        />
        <div className="min-w-0 flex-1">
          <b className="block text-[16px] leading-tight tracking-[-0.01em]">{agent.name}</b>
          <span className="mt-0.5 block font-mono text-[11.5px] text-[var(--g-ink-3)]">
            {agent.modelLine}
          </span>
        </div>
        <MiniButton go href="/console" className="flex-none self-start">
          Talk →
        </MiniButton>
      </div>

      {/* standing orders */}
      <div className="mx-[20px] rounded-[9px] border border-dashed border-[var(--g-hairline)] px-[13px] py-[10px] text-[12px] leading-[1.6] text-[var(--g-ink-2)]">
        <span className="mr-[6px] font-mono text-[var(--g-ink-3)]">§</span>
        {agent.standingOrders}
      </div>

      {/* autonomy dial */}
      <div className="mx-[20px] mt-[12px] overflow-hidden rounded-[9px] border border-[var(--g-hairline)]">
        <div className="flex text-center text-[10px] font-semibold">
          {agent.dial.map((tier, i) => (
            <span
              key={i}
              className={`flex-1 border-l border-[var(--g-hairline-soft)] px-[4px] py-[6px] first:border-l-0 ${
                tier.active
                  ? "bg-[rgba(17,130,123,0.13)] text-[var(--agent)]"
                  : "text-[var(--g-ink-3)]"
              }`}
            >
              {tier.label}
            </span>
          ))}
        </div>
      </div>

      {/* stats strip */}
      <div className="mt-[4px] flex border-t border-[var(--g-hairline-soft)]">
        {agent.stats.map((stat, i) => (
          <div
            key={i}
            className="flex-1 border-l border-[var(--g-hairline-soft)] px-[20px] py-[10px] first:border-l-0"
          >
            <b className="block text-[15px]">{stat.value}</b>
            <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-[var(--g-ink-3)]">{stat.label}</span>
          </div>
        ))}
      </div>

      {/* recent decisions (incl. declines & escalations) */}
      {agent.decisions.map((dec, i) => (
        <DecisionRow key={i} decision={dec} />
      ))}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* DECISION ROW                                                          */
/* ------------------------------------------------------------------ */

function DecisionRow({ decision }: { decision: AgentDecision }) {
  const glyph =
    decision.tone === "decline"
      ? "↳ declined:"
      : decision.tone === "escalate"
      ? "↳ escalated:"
      : "↳";

  return (
    <div className="flex items-baseline gap-[10px] border-t border-[var(--g-hairline-soft)] px-[20px] py-[9px] text-[12px] text-[var(--g-ink-2)]">
      <span
        className={
          decision.tone === "decline"
            ? "text-[var(--cost)] font-mono text-[10px]"
            : decision.tone === "escalate"
            ? "text-[var(--cliff)] font-mono text-[10px]"
            : "font-mono text-[10px] text-[var(--g-ink-3)]"
        }
      >
        {glyph}
      </span>
      <span className="flex-1 leading-relaxed">{decision.text}</span>
      <span className="ml-auto whitespace-nowrap font-mono text-[9.5px] text-[var(--g-ink-3)]">{decision.time}</span>
    </div>
  );
}
