"use client";

// Surface 01 — THE DESK (firm command deck). The firm's morning surface: what
// needs a human (the sign-off queue), where the season stands, and the book
// pulse ranked by what the engines can still recover.
//
// [live] GET /agents/scan-book (the book pulse — kept in the backend's
//   savings-ranked order, NOT re-sorted by total_tax) · GET /clients + each
//   /clients/:id/overview (snapshot + strategies + quarterly + years) · GET
//   /admin/tax-bracket-sets (micro-strata spans + the constants card) · GET
//   /memos/pending (drafted memos join the sign-off queue) · GET
//   /lifecycle/journal?tail=20 (the ticker is the audit-journal tail; its
//   chain_intact drives the "ledger verified" mark). The unsealed-plan queue
//   items are derived from real plan state.
// [live] GET /agents/registry (the duty band — the app's agent-backed capability
//   roster with per-capability presence + last journal activity).
// [additive] (honestly labeled): low-confidence-extraction queue items (need a
//   per-client extraction list).

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { currentBusinessQuarter } from "@/lib/time";
import {
  Panel, PanelHead, MicroLabel, Annotation, Chip, Money, Cavatar, Aavatar, WorkingDots,
  MiniButton, Stamp, QueueItem, Ticker, Omnibar, PositionInstrument, hueForClient,
  AGENT_HUES, type Segment,
} from "@/components/kit";

/** Compact relative time for the journal ticker ("12s", "4m", "2h", "3d"). */
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

/* ---- live shapes (same as Book/Season) ---- */
interface ScanRow { client_id: string; client_name: string }
interface ClientRow { id: string; display_name: string; filing_status_default: string; primary_state: string | null; status: string }
interface Snapshot { taxable_income_cents: number; total_tax_cents: number; marginal_rate: string }
interface YearRow { id: string; tax_year: number; role: string; filing_status: string; finalized_at: string | null; snapshot: Snapshot | null }
interface StrategyRow { id: string; name: string; disposition: string; estimated_savings_cents: number }
interface QuarterRow { quarter: number; due_date: string; required_payment_cents: number; payment_made_cents: number; unpaid_rollforward_cents: number; status: string }
interface Overview {
  client: { id: string; display_name: string; filing_status_default: string; primary_state: string | null };
  years: YearRow[]; base_year_id: string | null; plan_year_id: string | null;
  strategies: StrategyRow[]; quarterly: QuarterRow[];
}
interface BracketRow { lower_bound_cents: number; upper_bound_cents: number | null; rate: string; ordinal: number }
interface BracketSet { id: string; tax_year: number; jurisdiction: string; filing_status: string; rows: BracketRow[] }

/* ---- live: drafted memos awaiting sign-off (GET /memos/pending) ---- */
interface PendingMemo {
  memo_id: string; client_tax_year_id: string; client_name: string; tax_year: number;
  version: number; created_at: string; total_savings_identified_cents: number | null;
}
/* ---- live: audit-journal tail (GET /lifecycle/journal?tail=20) ---- */
interface JournalEvent {
  id: string; created_at: string; event_type: string; actor_uc_uid: string;
  aggregate_type: string; aggregate_id: string; payload: Record<string, unknown>;
  hash: string; prev_hash: string | null;
}
interface JournalStatus { count: number; latest_hash: string | null; latest_at: string | null; chain_intact: boolean }
interface JournalTail { events: JournalEvent[]; status: JournalStatus }

function buildSegments(sets: BracketSet[], year: number, filing: string): Segment[] {
  if (!sets.length) return [];
  const fed = sets.filter((s) => s.jurisdiction?.toLowerCase().includes("fed"));
  const pool = fed.length ? fed : sets;
  const set = pool.find((s) => s.tax_year === year && s.filing_status === filing) ?? pool.find((s) => s.filing_status === filing) ?? pool[0];
  if (!set) return [];
  const rows = [...set.rows].sort((a, b) => a.lower_bound_cents - b.lower_bound_cents);
  const topLower = rows[rows.length - 1]?.lower_bound_cents ?? 0;
  const cap = topLower + 150_000_00;
  return rows.map((r, i) => ({ rate: Number(r.rate), fromCents: r.lower_bound_cents, toCents: r.upper_bound_cents ?? (i === rows.length - 1 ? cap : r.lower_bound_cents) }));
}

/* ---- [live] duty band — GET /agents/registry. The app's agent-backed capability
   roster; each capability's presence + last activity is derived from the audit
   journal by the backend (status=available when the journal shows a mapped event,
   else idle). ---- */
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

/** Tone the avatar/presence by kind: agents wear the strategist teal, engines &
 *  services take a muted, kind-distinct hue. (The registry keys aren't the kit's
 *  four AgentKeys, so we hue by kind rather than by key.) */
function hueForKind(kind: RegistryAgent["kind"]): string {
  if (kind === "agent") return AGENT_HUES.strategist;   // teal — the LLM-backed staff
  if (kind === "service") return AGENT_HUES.clerk;      // steel-blue — extraction/service
  return AGENT_HUES.bookrunner;                          // olive — deterministic engine
}

/** Humanize an audit event_type into "what it last did" ("memo.signed" →
 *  "memo signed", "return_document_uploaded" → "return document uploaded"). */
function lastDid(eventType: string | null): string {
  if (!eventType) return "";
  return eventType.replace(/[._]/g, " ");
}

const Q_NODES = [
  { label: "APR 15", q: 1 }, { label: "JUN 15", q: 2 }, { label: "SEP 15", q: 3 }, { label: "JAN 15", q: 4 },
];
export default function DeskPage() {
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [scanOrder, setScanOrder] = useState<string[] | null>(null);
  const [overviews, setOverviews] = useState<Record<string, Overview>>({});
  const [sets, setSets] = useState<BracketSet[]>([]);
  const [pendingMemos, setPendingMemos] = useState<PendingMemo[]>([]);
  const [journal, setJournal] = useState<JournalTail | null>(null);
  // [live] duty band roster (null = loading; [] = empty/unavailable → honest empty state)
  const [duty, setDuty] = useState<RegistryAgent[] | null>(null);

  useEffect(() => { api.get("/clients").then((r) => setClients(Array.isArray(r.data) ? r.data : (r.data?.clients ?? []))).catch(() => setClients([])); }, []);
  // [live] agent registry — the duty band's presence + last activity
  useEffect(() => { api.get<{ agents: RegistryAgent[] }>("/agents/registry").then((r) => setDuty(Array.isArray(r.data?.agents) ? r.data.agents : [])).catch(() => setDuty([])); }, []);
  useEffect(() => { api.get("/admin/tax-bracket-sets").then((r) => setSets(r.data)).catch(() => setSets([])); }, []);
  // [live] drafted memos awaiting sign-off — folded into the queue below
  useEffect(() => { api.get<PendingMemo[]>("/memos/pending").then((r) => setPendingMemos(Array.isArray(r.data) ? r.data : [])).catch(() => setPendingMemos([])); }, []);
  // [live] audit-journal tail — drives the ticker + the ledger-verified mark
  useEffect(() => { api.get<JournalTail>("/lifecycle/journal?tail=20").then((r) => setJournal(r.data)).catch(() => setJournal(null)); }, []);
  useEffect(() => {
    // keep scan-book's savings ranking (do NOT re-sort by total_tax — spec §11)
    api.get("/agents/scan-book").then((r) => {
      const rows: ScanRow[] = Array.isArray(r.data) ? r.data : (r.data?.results ?? r.data?.clients ?? []);
      setScanOrder(rows.map((x) => x.client_id).filter(Boolean));
    }).catch(() => setScanOrder([]));
  }, []);
  useEffect(() => {
    if (!clients) return;
    for (const c of clients) {
      if (overviews[c.id]) continue;
      api.get(`/clients/${c.id}/overview`).then((r) => setOverviews((p) => ({ ...p, [c.id]: r.data }))).catch(() => undefined);
    }
  }, [clients, overviews]);

  /* ---- book pulse: scan-book order if present, else by recoverable savings ---- */
  const rankedClients = useMemo(() => {
    const list = clients ?? [];
    const savings = (id: string) => (overviews[id]?.strategies ?? []).reduce((a, s) => a + (s.estimated_savings_cents || 0), 0);
    if (scanOrder && scanOrder.length) {
      const idx = new Map(scanOrder.map((id, i) => [id, i]));
      return [...list].sort((a, b) => (idx.get(a.id) ?? 999) - (idx.get(b.id) ?? 999));
    }
    return [...list].sort((a, b) => savings(b.id) - savings(a.id));
  }, [clients, scanOrder, overviews]);

  const identifiedTotal = useMemo(
    () => Object.values(overviews).reduce((a, ov) => a + ov.strategies.reduce((s, x) => s + (x.estimated_savings_cents || 0), 0), 0),
    [overviews],
  );
  const signedTotal = useMemo(
    () => Object.values(overviews).reduce((a, ov) => a + ov.strategies.filter((s) => ["signed", "accepted", "implementing"].includes(s.disposition)).reduce((s, x) => s + (x.estimated_savings_cents || 0), 0), 0),
    [overviews],
  );

  /* ---- map a memo's tax-year id back to its client via loaded overviews ---- */
  const clientForTaxYear = useMemo(() => {
    const m = new Map<string, string>();
    for (const [clientId, ov] of Object.entries(overviews)) {
      for (const y of ov.years) m.set(y.id, clientId);
    }
    return m;
  }, [overviews]);

  /* ---- sign-off queue: drafted memos [live] + unsealed plans + baseline review ---- */
  const queue = useMemo(() => {
    const items: { id: string; kind: "memo" | "plan" | "intake"; client: string; clientId: string | null; sub: string; href: string }[] = [];
    // [live] drafted memos awaiting signature — the truest "sign the memo" work
    for (const m of pendingMemos) {
      const clientId = clientForTaxYear.get(m.client_tax_year_id) ?? null;
      const saved = m.total_savings_identified_cents;
      const savedNote = saved && saved > 0 ? `${centsToUSD(saved)} identified · ` : "";
      items.push({
        id: `memo-${m.memo_id}`, kind: "memo", client: m.client_name, clientId,
        sub: `${savedNote}draft v${m.version} · TY ${m.tax_year} — review, edit, or sign to seal`,
        // resolvable → deep-link the client's memo; otherwise the firm-wide book (no tax-year memo route)
        href: clientId ? `/c/${clientId}/memo` : "/book",
      });
    }
    for (const c of clients ?? []) {
      const ov = overviews[c.id];
      if (!ov) continue;
      const plan = ov.years.find((y) => y.id === (ov.plan_year_id ?? ov.base_year_id));
      const sumSaved = ov.strategies.reduce((s, x) => s + (x.estimated_savings_cents || 0), 0);
      if (plan && !plan.finalized_at && ov.strategies.length > 0) {
        items.push({ id: c.id, kind: "plan", client: ov.client.display_name, clientId: c.id, sub: `${ov.strategies.length} strategies · ${centsToUSD(sumSaved)} identified — finalize locks the year & stamps the hash`, href: `/c/${c.id}/plan` });
      } else if (!plan?.snapshot) {
        items.push({ id: c.id, kind: "intake", client: ov.client.display_name, clientId: c.id, sub: "baseline not confirmed — review the import before it locks", href: `/c/${c.id}/return` });
      }
    }
    return items;
  }, [clients, overviews, pendingMemos, clientForTaxYear]);

  /* ---- season: quarterly across the book ---- */
  const qNum = currentBusinessQuarter();
  const season = useMemo(() => {
    const rows: { name: string; status: string; tone: "save" | "cost" | "neutral"; amount: number }[] = [];
    let unfunded = 0;
    for (const c of clients ?? []) {
      const ov = overviews[c.id]; if (!ov) continue;
      const q = ov.quarterly.find((x) => x.quarter === qNum);
      if (!q) { rows.push({ name: ov.client.display_name, status: "—", tone: "neutral", amount: 0 }); continue; }
      if (q.status === "paid" || q.unpaid_rollforward_cents === 0) rows.push({ name: ov.client.display_name, status: q.payment_made_cents > 0 ? `PAID ${centsToUSD(q.payment_made_cents)}` : "W/H COVERS", tone: "save", amount: 0 });
      else { rows.push({ name: ov.client.display_name, status: `DUE ${centsToUSD(q.unpaid_rollforward_cents)}`, tone: "cost", amount: q.unpaid_rollforward_cents }); unfunded++; }
    }
    return { rows, unfunded };
  }, [clients, overviews, qNum]);

  const fedSet = sets.find((s) => s.jurisdiction?.toLowerCase().includes("fed")) ?? sets[0];

  /* ---- ticker = the audit-journal tail [live]; falls back to derived metrics
     while the journal is empty/unavailable (e.g. a brand-new workspace) ---- */
  const tickItems = useMemo(() => {
    const evs = journal?.events ?? [];
    if (evs.length > 0) {
      return evs.map((e) => {
        const t = e.event_type.toLowerCase();
        const tone: "save" | "cost" | "seal" | "agent" =
          /sign|seal|finaliz|lock/.test(t) ? "seal" : /declin|reject|flag|fail|void/.test(t) ? "cost" : "agent";
        const label = `${e.event_type.replace(/[._]/g, " ")} · ${e.aggregate_type}`;
        return { tone, label, value: `${e.hash.slice(0, 8)} · ${relTime(e.created_at)} ago` };
      });
    }
    // derived fallback — clearly not the journal; same shape the v1 surface used
    return [
      { tone: "seal" as const, label: "your sign-off", value: `${queue.length} waiting` },
      { tone: "save" as const, label: "identified this season", value: centsToUSD(identifiedTotal) },
      { tone: "cost" as const, label: `Q${qNum} unfunded`, value: `${season.unfunded} clients` },
      { tone: "agent" as const, label: "engines on", value: `${fedSet?.tax_year ?? 2026} constants · golden-tested` },
    ];
  }, [journal, queue.length, identifiedTotal, season.unfunded, qNum, fedSet]);
  const ledgerVerified = journal?.status.chain_intact ?? null;

  const loading = clients === null;

  return (
    <div className="wrap py-7 pb-16">
      {/* ===== header ===== */}
      <section className="rise">
        <MicroLabel>The desk · planning year {fedSet?.tax_year ?? 2026}</MicroLabel>
        <h1 className="mt-2 text-[38px] font-extrabold leading-[1.08] tracking-[-0.025em]">
          {season.unfunded > 0 ? <>Q{qNum} estimates are due.<br />{queue.length} item{queue.length === 1 ? "" : "s"} need your signature.</> : <>The book is current.<br />{queue.length} item{queue.length === 1 ? "" : "s"} on your desk.</>}
        </h1>
        <Annotation className="mt-1 block">The strategist works the file. You sign the memo.</Annotation>
        <div className="mt-3.5 flex flex-wrap gap-x-6 gap-y-1.5 text-[12.5px] text-[var(--g-ink-3)]">
          <span><b className="text-[var(--g-ink)]">{clients?.length ?? "—"}</b> clients</span>
          <span>identified <Money cents={identifiedTotal} tone="save" /></span>
          <span>signed <Money cents={signedTotal} tone="seal" /></span>
          <span>your sign-off <b className="text-[var(--g-ink)]">{queue.length}</b></span>
        </div>
      </section>

      {/* season strip */}
      {season.unfunded > 0 ? (
        <div className="rise d1 mt-5 flex items-center gap-4 rounded-[12px] border border-[color-mix(in_srgb,var(--cost)_35%,transparent)] bg-[linear-gradient(90deg,var(--cost-soft),transparent_60%)] px-[18px] py-3">
          <span className="fig text-[24px] font-semibold tracking-[-0.04em] tone-cost">Q{qNum}</span>
          <span className="text-[12.5px] text-[var(--g-ink-2)]">{season.unfunded} of {clients?.length ?? 0} clients have an unpaid estimate this quarter. Vouchers stage on the season board.</span>
          <Link href="/season" className="mini-btn go ml-auto">Open the season board</Link>
        </div>
      ) : null}

      {/* omnibar */}
      <div className="mt-5"><Omnibar placeholder="Ask the desk — who is within $25k of an IRMAA cliff if we convert this year?" /></div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Chip href="/console">scan the book again</Chip>
        <Chip href="/console">who hasn&apos;t paid this quarter?</Chip>
        <Chip href="/playbook">what changed in the constants?</Chip>
        <Chip tone="agent" href="/staff">● staff</Chip>
      </div>

      {/* ticker — [live] the audit-journal tail (newest events scrolling); a tiny
          "ledger verified" mark when the hash chain still checks. Falls back to
          derived metrics only while the journal is empty/unavailable. */}
      <div className="mt-5 flex items-center gap-3">
        <Ticker className="min-w-0 flex-1" items={tickItems} />
        {ledgerVerified !== null ? (
          <span className={`hidden shrink-0 font-mono text-[10px] sm:inline ${ledgerVerified ? "tone-save" : "tone-cost"}`} title={journal?.status.latest_hash ? `chain head ${journal.status.latest_hash.slice(0, 12)}` : undefined}>
            {ledgerVerified ? "● ledger verified" : "● ledger broken"}
          </span>
        ) : null}
      </div>

      <div className="mt-6 grid items-start gap-[22px] lg:grid-cols-[1.62fr_1fr]">
        <div className="flex flex-col gap-[22px]">
          {/* ===== sign-off queue ===== */}
          <Panel className="rise d3">
            <PanelHead>
              <MicroLabel><span className="tone-seal">Your sign-off</span></MicroLabel>
              <Annotation className="!text-[13px]">the only queue that blocks the practice</Annotation>
              <span className="ml-auto font-mono text-[11px] tone-seal">{queue.length} waiting</span>
            </PanelHead>
            {loading ? (
              <div className="p-5"><div className="skeleton h-16 w-full" /></div>
            ) : queue.length === 0 ? (
              <div className="px-5 py-8 text-center text-[13px] text-[var(--g-ink-3)]">Nothing waiting — the desk is clear.</div>
            ) : (
              queue.map((it) => (
                <QueueItem
                  key={it.id}
                  lead={<Cavatar name={it.client} hue={hueForClient(it.clientId ?? it.id)} className="!h-[34px] !w-[34px]" />}
                  title={it.kind === "memo" ? `Memo drafted — ${it.client}` : it.kind === "plan" ? `Plan ready to seal — ${it.client}` : `Baseline review — ${it.client}`}
                  sub={it.sub}
                  badge={<Stamp kind={it.kind === "intake" ? "flag" : "draft"} className="!transform-none !text-[9px]">{it.kind === "memo" ? "drafted" : it.kind === "plan" ? "unsealed" : "intake"}</Stamp>}
                  actions={<MiniButton href={it.href} seal={it.kind !== "intake"} go={it.kind === "intake"}>{it.kind === "memo" ? "Review & sign" : it.kind === "plan" ? "Finalize & seal" : "Review"}</MiniButton>}
                />
              ))
            )}
            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2 font-mono text-[10px] text-[var(--g-ink-3)]">
              <span className="tone-seal">[live]</span> drafted memos (GET /memos/pending) · <span className="tone-cost">[additive]</span> low-confidence-extraction items join with the per-client extraction list.
            </div>
          </Panel>

          {/* ===== book pulse ===== */}
          <Panel className="rise d4">
            <PanelHead>
              <MicroLabel>Book pulse</MicroLabel>
              <Annotation className="!text-[13px]">re-ranked by what the engines can still recover</Annotation>
              <Link href="/book" className="chip ml-auto">Open the book →</Link>
            </PanelHead>
            {loading ? <div className="p-5"><div className="skeleton h-20 w-full" /></div> : null}
            {rankedClients.map((c) => {
              const ov = overviews[c.id];
              const plan = ov?.years.find((y) => y.id === (ov.plan_year_id ?? ov.base_year_id)) ?? ov?.years[0];
              const snap = plan?.snapshot;
              const saved = (ov?.strategies ?? []).reduce((a, s) => a + (s.estimated_savings_cents || 0), 0);
              const signed = (ov?.strategies ?? []).some((s) => ["signed", "accepted", "implementing"].includes(s.disposition));
              const segs = snap && plan ? buildSegments(sets, plan.tax_year, plan.filing_status) : [];
              return (
                <Link key={c.id} href={`/c/${c.id}`} className="grid grid-cols-[auto_1.2fr_140px_auto] items-center gap-4 border-t border-[var(--g-hairline-soft)] px-[18px] py-3.5 no-underline transition-colors hover:bg-[var(--wash)]">
                  <Cavatar name={c.display_name} hue={hueForClient(c.id)} />
                  <div>
                    <div className="text-[14px] font-semibold tracking-[-0.01em] text-[var(--g-ink)]">{c.display_name}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-[var(--g-ink-3)]">{c.filing_status_default}{c.primary_state ? ` · ${c.primary_state}` : ""}{snap ? ` · ${(Number(snap.marginal_rate) * 100).toFixed(0)}% marginal` : ""}</div>
                  </div>
                  <div>{segs.length > 0 && snap ? <PositionInstrument variant="micro" segments={segs} incomeCents={snap.taxable_income_cents} /> : <span className="font-mono text-[10px] text-[var(--g-ink-3)]">{ov ? "no baseline" : "…"}</span>}</div>
                  <div className="text-right">
                    {saved > 0 ? <Money cents={saved} tone={signed ? "seal" : "save"} className="text-[15px] font-bold" /> : <span className="text-[15px] text-[var(--g-ink-3)]">—</span>}
                    <div className="font-mono text-[10px] text-[var(--g-ink-3)]">{signed ? "signed" : saved > 0 ? "identified" : "in progress"}</div>
                  </div>
                </Link>
              );
            })}
          </Panel>
        </div>

        {/* ===== right column ===== */}
        <div className="flex flex-col gap-[22px]">
          {/* duty band — [live] GET /agents/registry */}
          <Panel className="rise d4">
            <PanelHead>
              <MicroLabel>On duty</MicroLabel>
              <Link href="/staff" className="chip agent ml-auto">Staff →</Link>
            </PanelHead>
            {duty === null ? (
              <div className="p-[18px]"><div className="skeleton h-14 w-full" /></div>
            ) : duty.length === 0 ? (
              <div className="px-[18px] py-7 text-center text-[12px] text-[var(--g-ink-3)]">No agents registered.</div>
            ) : (
              duty.map((a) => {
                const idle = a.status === "idle";
                const did = lastDid(a.last_event_type);
                return (
                  <div key={a.key} className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-[18px] py-3 first:border-t-0">
                    <Aavatar name={a.name} hue={hueForKind(a.kind)} idle={idle} />
                    <div className="min-w-0">
                      <b className="block text-[13px] font-semibold">{a.name}</b>
                      <span className="block truncate text-[11.5px] text-[var(--g-ink-3)]">{a.role}</span>
                      {a.capabilities.length > 0 ? (
                        <span className="mt-0.5 block truncate font-mono text-[10px] text-[var(--g-ink-3)]">{a.capabilities.join(" · ")}</span>
                      ) : null}
                    </div>
                    <div className="ml-auto whitespace-nowrap text-right text-[11.5px] text-[var(--g-ink-2)]">
                      {did ? (
                        <>{did}{a.last_event_at ? <span className="ml-1 font-mono text-[10px] text-[var(--g-ink-3)]">{relTime(a.last_event_at)} ago</span> : null}{!idle ? <WorkingDots className="ml-1" /> : null}</>
                      ) : (
                        <span className="text-[var(--g-ink-3)]">idle</span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
            <div className="border-t border-[var(--g-hairline-soft)] px-[18px] py-1.5 font-mono text-[10px] text-[var(--g-ink-3)]"><span className="tone-seal">[live]</span> presence + last activity from the agent registry (GET /agents/registry)</div>
          </Panel>

          {/* the season at a glance — real quarterly */}
          <Panel className="rise d5">
            <PanelHead>
              <MicroLabel>The season</MicroLabel>
              <Chip tone="cost" className="ml-auto">Q{qNum}{season.unfunded > 0 ? ` · ${season.unfunded} unfunded` : ""}</Chip>
            </PanelHead>
            <div className="flex items-center px-[18px] pb-2 pt-4">
              {Q_NODES.map((n) => (
                <div key={n.q} className="relative flex flex-1 flex-col items-center gap-1.5">
                  <i className={`h-[11px] w-[11px] rounded-full border-[1.5px] ${n.q < qNum ? "border-[var(--save)] bg-[var(--save)]" : n.q === qNum ? "border-[var(--cost)] bg-[var(--cost)] shadow-[0_0_0_4px_var(--cost-soft)]" : "border-[var(--g-ink-3)] bg-[var(--g-surface-2)]"}`} />
                  <small className={`font-mono text-[9px] ${n.q === qNum ? "font-semibold tone-cost" : "text-[var(--g-ink-3)]"}`}>{n.label}{n.q < qNum ? " ✓" : ""}</small>
                </div>
              ))}
            </div>
            <div className="px-[18px] pb-2.5 pt-1">
              {season.rows.map((r, i) => (
                <div key={i} className="flex justify-between border-t border-[var(--g-hairline-soft)] py-2 text-[12.5px] first:border-t-0">
                  <span>{r.name}</span>
                  <span className={`font-mono text-[10.5px] ${r.tone === "save" ? "tone-save" : r.tone === "cost" ? "tone-cost" : "text-[var(--g-ink-3)]"}`}>{r.status}</span>
                </div>
              ))}
            </div>
          </Panel>

          {/* the constants — real bracket year + citations */}
          <Panel className="rise d6 p-[18px]">
            <MicroLabel>The constants under everything</MicroLabel>
            <div className="mt-2 space-y-1.5 text-[12.5px] text-[var(--g-ink-2)]">
              <div className="flex items-baseline gap-2">{fedSet?.tax_year ?? 2026} ordinary + LTCG brackets <code className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]">tax-bracket-sets</code></div>
              <div className="flex items-baseline gap-2">QBI thresholds $201,750 / $403,500 <code className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]">§199A</code></div>
              <div className="flex items-baseline gap-2">IRMAA tiers + AMT exemption <code className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]">CMS · OBBBA</code></div>
            </div>
            <div className="mt-2.5 flex items-center border-t border-[var(--g-hairline-soft)] pt-2.5">
              <Stamp kind="verified" className="!transform-none">golden-tested</Stamp>
              <Link href="/playbook" className="chip ml-auto">Inspect the tables →</Link>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
