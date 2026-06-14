"use client";

// Surface 01 — THE DESK (firm command deck). The firm's morning surface: what
// needs a human (the sign-off queue), where the season stands, and the book
// pulse ranked by what the engines can still recover.
//
// [live] GET /agents/scan-book (the book pulse — kept in the backend's
//   savings-ranked order, NOT re-sorted by total_tax) · GET /clients + each
//   /clients/:id/overview (snapshot + strategies + quarterly + years) · GET
//   /admin/tax-bracket-sets (micro-strata spans + the constants card).
// [additive] (honestly labeled): drafted-memo + extraction queue items (need
//   memo persistence / per-client extraction list); the duty band (agent
//   registry); the ticker (audit-journal tail). The unsealed-plan queue items
//   are derived from real plan state.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import {
  Panel, PanelHead, MicroLabel, Annotation, Chip, Money, Cavatar, Aavatar, WorkingDots,
  MiniButton, Stamp, QueueItem, Ticker, Omnibar, PositionInstrument, hueForClient,
  type Segment, type AgentKey,
} from "@/components/kit";

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

/* ---- [additive] duty band — agent registry has no endpoint yet (like Staff).
   TODO(integration: GET /agents/registry) — render real presence/last-run. ---- */
const DUTY: { key: AgentKey; name: string; role: string; doing: string; idle?: boolean }[] = [
  { key: "strategist", name: "The Strategist", role: "memos · optimizers · engine-only figures", doing: "ready" },
  { key: "clerk", name: "The Intake Clerk", role: "1040 vision OCR · field confidence", doing: "idle", idle: true },
  { key: "bookrunner", name: "The Bookrunner", role: "book scan · opportunity ranking", doing: "book ranked", idle: true },
  { key: "liaison", name: "The AO Liaison", role: "pulls P&L from the firm's books", doing: "federation ✓", idle: true },
];

const Q_NODES = [
  { label: "APR 15", q: 1 }, { label: "JUN 15", q: 2 }, { label: "SEP 15", q: 3 }, { label: "JAN 15", q: 4 },
];
function currentQuarter(): number { const m = new Date().getMonth() + 1; return m <= 4 ? 1 : m <= 6 ? 2 : m <= 9 ? 3 : 4; }

export default function DeskPage() {
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [scanOrder, setScanOrder] = useState<string[] | null>(null);
  const [overviews, setOverviews] = useState<Record<string, Overview>>({});
  const [sets, setSets] = useState<BracketSet[]>([]);

  useEffect(() => { api.get("/clients").then((r) => setClients(Array.isArray(r.data) ? r.data : (r.data?.clients ?? []))).catch(() => setClients([])); }, []);
  useEffect(() => { api.get("/admin/tax-bracket-sets").then((r) => setSets(r.data)).catch(() => setSets([])); }, []);
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

  /* ---- sign-off queue (from real plan state) ---- */
  const queue = useMemo(() => {
    const items: { id: string; kind: "plan" | "intake"; client: string; clientId: string; sub: string; href: string }[] = [];
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
  }, [clients, overviews]);

  /* ---- season: quarterly across the book ---- */
  const qNum = currentQuarter();
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

  const loading = clients === null;
  const fedSet = sets.find((s) => s.jurisdiction?.toLowerCase().includes("fed")) ?? sets[0];

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

      {/* ticker — [additive] audit-journal tail; until then a derived recent-activity line */}
      {queue.length > 0 ? (
        <Ticker className="mt-5" items={[
          { tone: "seal", label: "your sign-off", value: `${queue.length} waiting` },
          { tone: "save", label: "identified this season", value: centsToUSD(identifiedTotal) },
          { tone: "cost", label: `Q${qNum} unfunded`, value: `${season.unfunded} clients` },
          { tone: "agent", label: "engines on", value: `${fedSet?.tax_year ?? 2026} constants · golden-tested` },
        ]} />
      ) : null}

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
                  lead={<Cavatar name={it.client} hue={hueForClient(it.clientId)} className="!h-[34px] !w-[34px]" />}
                  title={it.kind === "plan" ? `Plan ready to seal — ${it.client}` : `Baseline review — ${it.client}`}
                  sub={it.sub}
                  badge={<Stamp kind={it.kind === "plan" ? "draft" : "flag"} className="!transform-none !text-[9px]">{it.kind === "plan" ? "unsealed" : "intake"}</Stamp>}
                  actions={<MiniButton href={it.href} seal={it.kind === "plan"} go={it.kind !== "plan"}>{it.kind === "plan" ? "Finalize & seal" : "Review"}</MiniButton>}
                />
              ))
            )}
            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2 font-mono text-[10px] text-[var(--g-ink-3)]">
              <span className="tone-cost">[additive]</span> drafted-memo + low-confidence-extraction items join here with memo persistence + the per-client extraction list.
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
          {/* duty band — [additive] fixture */}
          <Panel className="rise d4">
            <PanelHead>
              <MicroLabel>On duty</MicroLabel>
              <Link href="/staff" className="chip agent ml-auto">Staff →</Link>
            </PanelHead>
            {DUTY.map((a) => (
              <div key={a.key} className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-[18px] py-3 first:border-t-0">
                <Aavatar name={a.name} agent={a.key} idle={a.idle} />
                <div><b className="block text-[13px] font-semibold">{a.name}</b><span className="text-[11.5px] text-[var(--g-ink-3)]">{a.role}</span></div>
                <div className="ml-auto text-right text-[11.5px] text-[var(--g-ink-2)]">{a.doing}{!a.idle ? <WorkingDots className="ml-1" /> : null}</div>
              </div>
            ))}
            <div className="border-t border-[var(--g-hairline-soft)] px-[18px] py-1.5 font-mono text-[10px] text-[var(--g-ink-3)]"><span className="tone-cost">[additive]</span> live presence from the agent registry</div>
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
