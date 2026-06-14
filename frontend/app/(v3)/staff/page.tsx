"use client";

// Surface 10 — THE STAFF
// Agents as staff: avatar + presence, model line, standing orders (§, editable),
// the autonomy dial, stats strip, recent decisions including declines/escalations.
// Three doors: Console / MCP / API + live traffic feed with verdicts.
// House rules HR-01…05. Audit chain verify chip.
//
// Live data wired:
//   GET /agents/registry            — the agent-backed capability roster (name,
//                                     role, kind, status, capabilities, last
//                                     journal activity). Powers the agent cards.
//   GET /agents/door-stats          — mutating journal events grouped by door
//                                     (gui/console/mcp/api). Powers the door panel.
//   GET /lifecycle/audit/verify     — { valid: boolean }
//   GET /lifecycle/journal?tail=20  — real MCP traffic feed (hash-chained journal tail)
//
// Still additive (spec §7-10, Honesty Protocol) — CLEARLY LABELED FIXTURES:
//   Header summary strip       — on-duty/actions-this-week/approval/inference
//                                (GET /agents/registry/stats — not built yet)
//   Ops recommendations        — GET /agents/recommendations (not built yet)
//   Standing orders / autonomy dial / per-agent stats & decisions are design copy,
//   not live per-agent data, so they are NOT rendered on the cards (Honesty Protocol).
//
// Per-surface integration TODO: frontend/INTEGRATION-TODO.10.md

import { useEffect, useState } from "react";
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
  AGENT_HUES,
} from "@/components/kit";

/* ------------------------------------------------------------------ */
/* LIVE wire shape                                                       */
/* ------------------------------------------------------------------ */

interface AuditVerifyResponse {
  valid: boolean;
}

// GET /lifecycle/journal?tail=20 — newest-first tail of the hash-chained journal
interface JournalEvent {
  id: string;
  created_at: string;
  event_type: string;
  actor_uc_uid: string;
  aggregate_type: string;
  aggregate_id: string;
  payload: Record<string, unknown>;
  hash: string;
  prev_hash: string | null;
}
interface JournalTail {
  events: JournalEvent[];
  status: {
    count: number;
    latest_hash: string | null;
    latest_at: string | null;
    chain_intact: boolean;
  };
}

// Compact relative time for the live traffic feed ("12s", "4m", "2h", "3d").
function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.round(hrs / 24)}d`;
}

/* ------------------------------------------------------------------ */
/* LIVE wire shapes — agent registry + door stats (spec §9.6)            */
/* ------------------------------------------------------------------ */

// GET /agents/registry — the app's agent-backed capability roster. Each entry's
// status + last activity is derived from the audit journal by the backend; it
// never claims activity the journal lacks.
interface RegistryAgent {
  key: string;
  name: string;
  role: string;
  kind: "engine" | "agent" | "service";
  status: "available" | "idle";
  last_event_at: string | null;
  last_event_type: string | null;
  capabilities: string[];
}

// GET /agents/door-stats — mutating journal events grouped by the door they came
// through, within a window. Counts mutating audit events, NOT all traffic.
interface DoorCount {
  door: string;
  count: number;
}
interface DoorStats {
  total: number;
  by_door: DoorCount[];
  window_days: number;
}

// Tone an agent by kind: agents wear the strategist teal; engines & services take
// a muted, kind-distinct hue. (Registry keys aren't the kit's four AgentKeys.)
function hueForKind(kind: RegistryAgent["kind"]): string {
  if (kind === "agent") return AGENT_HUES.strategist;
  if (kind === "service") return AGENT_HUES.clerk;
  return AGENT_HUES.bookrunner;
}

// Humanize an audit event_type ("memo.signed" → "memo signed").
function humanizeEvent(eventType: string | null): string {
  if (!eventType) return "";
  return eventType.replace(/[._]/g, " ");
}

// Human label for a door key; unknown values surface verbatim.
const DOOR_LABELS: Record<string, string> = {
  gui: "GUI — the app",
  console: "Console — you",
  mcp: "MCP — agents & Claude",
  api: "API — services",
};

// LIVE: GET /lifecycle/journal?tail=20 powers the MCP traffic feed (rows built
// from real JournalEvents below).

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
  const [journal, setJournal] = useState<JournalEvent[] | null>(null);
  // LIVE: agent registry + door stats (null = loading; [] / null on error)
  const [agents, setAgents] = useState<RegistryAgent[] | null>(null);
  const [doors, setDoors] = useState<DoorStats | null>(null);

  // LIVE: GET /lifecycle/audit/verify
  useEffect(() => {
    api
      .get<AuditVerifyResponse>("/lifecycle/audit/verify")
      .then((r) => setAuditValid(r.data.valid))
      .catch(() => setAuditValid(null))
      .finally(() => setAuditLoading(false));
  }, []);

  // LIVE: GET /lifecycle/journal?tail=20 — real MCP traffic feed (newest-first)
  useEffect(() => {
    api
      .get<JournalTail>("/lifecycle/journal", { params: { tail: 20 } })
      .then((r) => setJournal(r.data.events ?? []))
      .catch(() => setJournal([]));
  }, []);

  // LIVE: GET /agents/registry — the agent cards
  useEffect(() => {
    api
      .get<{ agents: RegistryAgent[] }>("/agents/registry")
      .then((r) => setAgents(Array.isArray(r.data?.agents) ? r.data.agents : []))
      .catch(() => setAgents([]));
  }, []);

  // LIVE: GET /agents/door-stats — the door-usage panel (mutating events, 30d)
  useEffect(() => {
    api
      .get<DoorStats>("/agents/door-stats", { params: { window_days: 30 } })
      .then((r) => setDoors(r.data))
      .catch(() => setDoors(null));
  }, []);

  // Doors to render: live by_door if present, else the four known doors at zero
  // so the panel stays legible before any mutating action exists.
  const doorRows: DoorCount[] =
    doors?.by_door && doors.by_door.length > 0
      ? doors.by_door
      : (["gui", "console", "mcp", "api"] as const).map((door) => ({ door, count: 0 }));
  const doorMax = Math.max(1, ...doorRows.map((d) => d.count));

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
        {/* on-duty is LIVE from the registry; the rest of this strip
            (weekly actions / approval / inference) needs GET /agents/registry/stats,
            which is not built yet — kept and labeled fixture (Honesty Protocol). */}
        {/* TODO(integration: GET /agents/registry/stats) — weekly actions, approval rate, inference cost */}
        <div className="ml-auto flex items-baseline gap-[20px] text-[12.5px] text-[var(--g-ink-3)]">
          <span>on duty <b className="text-[var(--g-ink)]">{agents ? agents.filter((a) => a.status === "available").length : "—"}</b></span>
          <span className="opacity-70">actions this week <b className="text-[var(--g-ink)]">312</b></span>
          <span className="opacity-70">approved <b className="text-[var(--g-ink)]">96%</b></span>
          <span className="opacity-70">inference this month <b className="fig text-[var(--g-ink)]">$0.00 — local</b></span>
          <span className="font-mono text-[10px] text-[var(--cost)]">[fixture]</span>
        </div>
      </section>

      {/* ---- honesty banner (Honesty Protocol) ---- */}
      <div className="rise d1 mt-3 rounded-[10px] border border-[color-mix(in_srgb,var(--save)_30%,transparent)] bg-[color-mix(in_srgb,var(--save)_6%,transparent)] px-4 py-2.5 font-mono text-[10.5px] text-[var(--g-ink-2)]">
        <span className="tone-save">[live]</span> Agent cards (GET /agents/registry), door usage (GET /agents/door-stats),
        {" "}the audit-chain chip (GET /lifecycle/audit/verify) and the MCP traffic feed (GET /lifecycle/journal?tail=20) all read real state.
        {" "}<span className="tone-cost">[fixture]</span> The header&apos;s weekly-actions / approval / inference figures and the ops recommendations below
        {" "}still await GET /agents/registry/stats + GET /agents/recommendations (spec §9.6).
      </div>

      {/* ---- agent crew (2-column grid) — [live] GET /agents/registry ---- */}
      {agents === null ? (
        <div className="rise d2 mt-5 grid grid-cols-1 gap-[22px] md:grid-cols-2">
          <div className="skeleton h-[180px] w-full rounded-[14px]" />
          <div className="skeleton h-[180px] w-full rounded-[14px]" />
        </div>
      ) : agents.length === 0 ? (
        <Panel className="rise d2 mt-5 px-5 py-8">
          <div className="text-center text-[13px] text-[var(--g-ink-3)]">No agents registered for this workspace.</div>
        </Panel>
      ) : (
        <div className="rise d2 mt-5 grid grid-cols-1 gap-[22px] md:grid-cols-2" style={{ alignItems: "start" }}>
          {agents.map((agent, i) => (
            <AgentCard key={agent.key} agent={agent} delay={i + 1} />
          ))}
        </div>
      )}

      {/* ---- the doors — [live] GET /agents/door-stats ---- */}
      <Panel className="rise d5 mt-[22px]">
        <PanelHead>
          <MicroLabel>The doors · actions by door (last {doors?.window_days ?? 30} days) — humans, agents & services enter the same engine through the same gate</MicroLabel>
          <span className="ml-auto">{auditChip}</span>
        </PanelHead>
        {/* door cells — counts of MUTATING audit events per door (not all traffic).
            Static grid (Tailwind JIT can't see a computed col count). */}
        <div className="grid grid-cols-2 sm:grid-cols-4">
          {doorRows.map((door) => {
            const label = DOOR_LABELS[door.door] ?? door.door;
            const pct = Math.round((door.count / doorMax) * 100);
            const hot = door.door === "mcp" && door.count > 0;
            return (
              <div
                key={door.door}
                className={`border-l border-t border-[var(--g-hairline-soft)] px-5 py-4 first:border-l-0 sm:border-t-0 ${hot ? "bg-[rgba(17,130,123,0.05)]" : ""}`}
              >
                <b className="block text-[14px]">{label}</b>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className="fig text-[22px] font-[750]">{door.count}</span>
                  <span className="text-[11px] text-[var(--g-ink-3)]">events</span>
                </div>
                {/* proportion bar across the doors */}
                <div className="mt-2 h-[5px] w-full overflow-hidden rounded-full bg-[var(--g-hairline-soft)]">
                  <div className="h-full rounded-full bg-[var(--agent)]" style={{ width: `${pct}%` }} />
                </div>
                <div className="mt-[5px] text-[11px] text-[var(--g-ink-3)]">
                  {door.count === 0 ? "no mutating actions yet" : `${doors?.total ? Math.round((door.count / doors.total) * 100) : 0}% of mutating actions`}
                </div>
              </div>
            );
          })}
        </div>
        <div className="border-t border-[var(--g-hairline-soft)] px-5 py-1.5 font-mono text-[10px] text-[var(--g-ink-3)]">
          <span className="tone-save">[live]</span> GET /agents/door-stats — counts <b>mutating</b> audit events (memo signs, confirms, plan writes…) stamped with their door, not all read traffic.
        </div>
        {/* traffic feed — LIVE: GET /lifecycle/journal?tail=20 (hash-chained journal tail) */}
        <div className="font-mono text-[10.5px]">
          {journal === null ? (
            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-[7px] text-[var(--g-ink-3)]">
              loading journal…
            </div>
          ) : journal.length === 0 ? (
            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-[7px] text-[var(--g-ink-3)]">
              no journal events yet — actions across the doors will appear here
            </div>
          ) : (
            journal.map((ev) => (
              <div
                key={ev.id}
                className="flex flex-wrap gap-[14px] border-t border-[var(--g-hairline-soft)] px-5 py-[7px] text-[var(--g-ink-3)]"
              >
                <b className="text-[var(--g-ink-2)] font-[500]">{ev.actor_uc_uid}</b>
                <span className="text-[var(--agent)]">{ev.event_type}</span>
                <span className="hidden sm:inline">{ev.aggregate_type}</span>
                <span className="hidden sm:inline">#{ev.hash.slice(0, 8)}</span>
                <span className="ml-auto">{relTime(ev.created_at)}</span>
              </div>
            ))
          )}
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
/* AGENT CARD — [live] one registry capability + its journal activity    */
/* ------------------------------------------------------------------ */

function AgentCard({ agent, delay }: { agent: RegistryAgent; delay: number }) {
  const idle = agent.status === "idle";
  const did = humanizeEvent(agent.last_event_type);

  return (
    <section className={`panel agentcard rise d${delay}`}>
      {/* top: avatar + identity + talk button */}
      <div className="flex gap-[14px] px-[20px] pb-[12px] pt-[18px]">
        <Aavatar
          name={agent.name}
          hue={hueForKind(agent.kind)}
          idle={idle}
          className="!h-[46px] !w-[46px] !text-[17px]"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <b className="block text-[16px] leading-tight tracking-[-0.01em]">{agent.name}</b>
            <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-[var(--g-ink-3)]">{agent.kind}</span>
          </div>
          <span className="mt-0.5 block text-[12px] leading-snug text-[var(--g-ink-2)]">{agent.role}</span>
          <span className={`mt-1 inline-flex items-center gap-1 font-mono text-[10px] ${idle ? "text-[var(--g-ink-3)]" : "tone-agent"}`}>
            <i className={`h-[6px] w-[6px] rounded-full ${idle ? "bg-[var(--g-ink-3)]" : "bg-[var(--agent)]"}`} />
            {agent.status}
          </span>
        </div>
        <MiniButton go href="/console" className="flex-none self-start">
          Talk →
        </MiniButton>
      </div>

      {/* capabilities — what this capability can actually do (from the roster) */}
      {agent.capabilities.length > 0 ? (
        <div className="mx-[20px] flex flex-wrap gap-1.5">
          {agent.capabilities.map((cap) => (
            <span key={cap} className="rounded-full border border-[var(--g-hairline)] bg-[var(--g-surface)] px-[9px] py-[3px] font-mono text-[10px] text-[var(--g-ink-2)]">
              {cap}
            </span>
          ))}
        </div>
      ) : null}

      {/* last activity — derived from the audit journal by the backend */}
      <div className="mt-[14px] flex items-baseline gap-[10px] border-t border-[var(--g-hairline-soft)] px-[20px] py-[10px] text-[12px] text-[var(--g-ink-2)]">
        <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-[var(--g-ink-3)]">last activity</span>
        {did ? (
          <>
            <span className="flex-1 leading-relaxed tone-agent">{did}</span>
            {agent.last_event_at ? (
              <span className="ml-auto whitespace-nowrap font-mono text-[9.5px] text-[var(--g-ink-3)]">{relTime(agent.last_event_at)} ago</span>
            ) : null}
          </>
        ) : (
          <span className="flex-1 leading-relaxed text-[var(--g-ink-3)]">no recorded activity yet</span>
        )}
      </div>
    </section>
  );
}
