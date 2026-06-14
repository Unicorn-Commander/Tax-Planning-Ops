"use client";

// Surface 06 — THE MEMORANDUM ★ (frontier). The product: an agent-drafted,
// advisor-curated, engine-footnoted document worth what the firm bills for it.
//
// Mostly LIVE: the strategist run (GET /agents/clients/tax-years/{id}/strategist)
// returns the memo prose, the findings, the savings, and the multi-year
// trajectory — all real engine output. The document Sheet renders them.
//
// [additive] (honestly marked, never faked):
//   - the literal engine-call trace + plan stream (the payload has no call list)
//   - memo persistence + versioning + sign/seal hash (signing is local-only v1)
//   - firm branding (GET /admin/branding) — defaults shown, TODO at the call site
//   - the Technical⟷Client-friendly register transform
// LLM narrates, engines compute — the model cannot invent a figure.

import { useMemo, useState } from "react";
import Link from "next/link";
import { Brain, Pencil, ArrowUpDown, EyeOff, Check } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  Panel, PanelHead, MicroLabel, Annotation, Money, Stamp, Button, MiniButton,
  WorkingDots, Dot, Sheet, Letterhead, SignoffBlock, Exhibit,
  ProvFigure, SourceMark, Omnibar, type Provenance,
} from "@/components/kit";

/* ---- the live strategist payload (same shape the Analysis tab reads) ---- */
interface Finding {
  title: string;
  category: string;
  recommended_action: string;
  estimated_impact_cents: number;
  impact_kind: "savings" | "cost" | "info";
  citation: string;
  caveat: string;
}
interface TrajectoryPoint { tax_year: number; total_tax_cents: number }
interface Trajectory { available: boolean; points: TrajectoryPoint[]; summary?: string }
interface Strategist {
  client_name: string;
  tax_year: number;
  current_total_tax_cents: number;
  marginal_rate: string;
  findings: Finding[];
  total_savings_identified_cents: number;
  memo: string | null;
  memo_available: boolean;
  objectives_summary: string | null;
  trajectory: Trajectory;
  disclaimer: string;
}

// TODO(integration: GET /admin/branding) — firm letterhead; default until it lands
const FIRM_NAME = "Northstar Tax Advisory";
const exhibitLetter = (i: number) => String.fromCharCode(65 + i);

export default function MemoPage() {
  const { overview, loading } = useClientOverview();
  const [strategist, setStrategist] = useState<Strategist | null>(null);
  const [signed, setSigned] = useState(false);
  const [hidden, setHidden] = useState<Set<number>>(new Set());

  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);
  const taxYearId = planYear?.id ?? null;

  const run = useAction(async () => {
    if (!taxYearId) return;
    const r = await api.get(`/agents/clients/tax-years/${taxYearId}/strategist`);
    setStrategist(r.data);
  });

  if (loading) return <div className="wrap py-7"><div className="skeleton h-[400px] w-full rounded-[14px]" /></div>;
  if (!overview || !planYear) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No tax year to memo yet</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">Confirm a return, then the strategist can draft.</p>
        </Panel>
      </div>
    );
  }

  const client = overview.client;
  const visibleFindings = (strategist?.findings ?? []).filter((_, i) => !hidden.has(i));
  const savingsFindings = visibleFindings.filter((f) => f.impact_kind === "savings");

  const headlineProv: Provenance | undefined = strategist ? {
    label: "identified, engine-verified",
    engine: "strategist · engines as tools",
    source: "engine",
    inputs: [
      { k: "findings", v: `${strategist.findings.length} (${savingsFindings.length} savings)` },
      { k: "current tax", v: centsToUSD(strategist.current_total_tax_cents) },
      { k: "marginal", v: `${(Number(strategist.marginal_rate) * 100).toFixed(1)}%` },
    ],
    auditRef: `tax-year ${taxYearId?.slice(0, 8)}`,
  } : undefined;

  return (
    <div className="wrap py-7 pb-20">
      {/* ===== the run theater ===== */}
      <Panel className="rise">
        <PanelHead>
          <Dot live={run.pending} />
          <MicroLabel><span className="tone-agent">{run.pending ? "Running…" : strategist ? "How this memo was built" : "The strategist drafts the memo"}</span></MicroLabel>
          <Annotation className="ml-auto !text-[13px]">the strategist calls engines as tools — engines compute, it narrates</Annotation>
        </PanelHead>

        <div className="grid gap-0 md:grid-cols-[1fr_300px]">
          <div className="border-r border-[var(--g-hairline-soft)] p-5">
            <MicroLabel>the plan</MicroLabel>
            <ol className="mt-2 space-y-1.5">
              {[
                "Read the verified return, the goals brief, and the multi-year trajectory",
                "Recompute the baseline on the current-year constants",
                "Run the optimizers across the situation",
                "Draft the memo — engine figures only, tied to stated goals",
              ].map((s, i) => (
                <li key={i} className="flex gap-2.5 text-[12.5px] text-[var(--g-ink-2)]">
                  <span className="fig flex-none text-[var(--g-ink-3)]">{strategist ? "✓" : i + 1}</span>{s}
                </li>
              ))}
            </ol>
            {run.pending ? (
              <div className="mt-3 inline-flex items-center gap-2 text-[12px] text-[var(--agent)]"><WorkingDots /> drafting on local inference…</div>
            ) : null}
            {run.error ? <p className="mt-3 text-[12.5px] text-[var(--cliff)]">{run.error}</p> : null}
            <div className="mt-3 inline-flex items-center gap-2 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-1.5 font-mono text-[10px] text-[var(--g-ink-3)]">
              <span className="dot" style={{ background: "var(--cost)" }} /> [additive] the literal engine-call trace + the priced-question rail stream with the run payload (spec §9.1).
            </div>
          </div>
          <div className="grid place-items-center p-5">
            {strategist ? (
              <div className="text-center">
                <Money cents={strategist.total_savings_identified_cents} tone="save" className="block text-[26px] font-bold" />
                <div className="mt-1 microlabel">identified · {strategist.findings.length} findings</div>
              </div>
            ) : (
              <Button variant="ink" icon={<Brain className="h-4 w-4" />} onClick={() => void run.run()} disabled={run.pending}>
                {run.pending ? "Running the strategist…" : "Run the strategist"}
              </Button>
            )}
          </div>
        </div>
      </Panel>

      {/* ===== the document ===== */}
      {strategist ? (
        <div className="rise d2 mt-7 grid justify-center gap-9 lg:grid-cols-[180px_minmax(0,860px)]">
          {/* sticky TOC */}
          <nav className="sticky top-[74px] hidden h-fit self-start text-[12px] lg:block">
            <MicroLabel>Memorandum</MicroLabel>
            <div className="mt-2.5 space-y-0.5">
              {["Summary", "The findings", "Engine notes"].map((t, i) => (
                <a key={t} href="#" className={`block border-l-[1.5px] py-1 pl-3 ${i === 0 ? "border-[var(--seal)] text-[var(--g-ink)]" : "border-[var(--g-hairline-soft)] text-[var(--g-ink-3)]"}`}>{t}</a>
              ))}
            </div>
            <div className="mt-4 font-mono text-[9.5px] leading-relaxed text-[var(--g-ink-3)]">
              {client.display_name.split(" ")[0]} · {strategist.tax_year}<br />
              {strategist.findings.length} findings<br />
              figures: <span className="text-[var(--agent)]">engine</span> · <span style={{ color: "#3f63a0" }}>doc</span> · <span className="text-[var(--seal)]">books</span>
            </div>
          </nav>

          {/* the sheet */}
          <Sheet className="px-[58px] py-[52px]">
            <Letterhead
              firm={<>{FIRM_NAME} <span className="ml-2 font-[var(--font-ui)] text-[10px] tracking-[0.14em] text-[var(--p-ink-3)]">MEMORANDUM</span></>}
              docRef={`${client.display_name} · ${strategist.tax_year}`}
            />
            <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-2 text-[13px]">
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Prepared for</div>{client.display_name}</div>
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Prepared by</div>The Strategist · reviewed by you</div>
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Re</div>{strategist.tax_year} tax position &amp; planning</div>
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Basis</div>verified return · live books · stated goals</div>
            </div>

            <h1 className="mt-7">{strategist.objectives_summary ? "Your plan, in one place." : `${strategist.tax_year}: where the leverage is.`}</h1>
            {strategist.objectives_summary ? <p className="lede mt-2">{strategist.objectives_summary}</p> : null}

            <div className="mt-6 flex items-end gap-6">
              <div>
                <div className="microlabel" style={{ color: "var(--p-ink-3)" }}>identified, engine-verified</div>
                <div className="font-[var(--font-ui)] text-[44px] font-bold leading-none tracking-[-0.03em] text-[var(--p-ink)]">
                  <ProvFigure cents={strategist.total_savings_identified_cents} prov={headlineProv} tone={undefined} />
                  <SourceMark source="engine" />
                </div>
              </div>
              <p className="max-w-[330px] pb-1.5 text-[13px] text-[var(--p-ink-2)]">
                Across {savingsFindings.length} engine-verified {savingsFindings.length === 1 ? "finding" : "findings"}, ordered below by impact. Current tax {centsToUSD(strategist.current_total_tax_cents)} at a {(Number(strategist.marginal_rate) * 100).toFixed(1)}% marginal rate.
              </p>
            </div>

            {/* the memo prose (the strategist's narration — engine numbers, plain words) */}
            {strategist.memo ? (
              <div className="mt-6">
                <h2><span className="no">I</span>The situation</h2>
                {strategist.memo.split(/\n\n+/).slice(0, 6).map((para, i) => (
                  <p key={i}>{para.trim()}</p>
                ))}
              </div>
            ) : null}

            {/* findings as curated exhibits */}
            <h2 className="mt-8"><span className="no">II</span>The findings</h2>
            {visibleFindings.length === 0 ? (
              <p className="text-[var(--p-ink-3)]">No findings — the strategist flagged nothing actionable this year.</p>
            ) : null}
            {strategist.findings.map((f, i) => {
              if (hidden.has(i)) return null;
              return (
                <Exhibit
                  key={i}
                  no={exhibitLetter(i)}
                  title={f.title}
                  impactCents={f.impact_kind !== "info" ? f.estimated_impact_cents : undefined}
                  impactKind={f.impact_kind === "cost" ? "cost" : "save"}
                  toolbar={
                    <>
                      <MiniButton>{<span className="inline-flex items-center gap-1"><Pencil className="h-3 w-3" /> Edit</span>}</MiniButton>
                      <MiniButton>{<span className="inline-flex items-center gap-1"><ArrowUpDown className="h-3 w-3" /> Reorder</span>}</MiniButton>
                      <MiniButton onClick={() => setHidden((h) => new Set(h).add(i))}>{<span className="inline-flex items-center gap-1"><EyeOff className="h-3 w-3" /> Hide</span>}</MiniButton>
                      <Link href={`/c/${client.id}/plan`} className="mini-btn seal inline-flex items-center gap-1"><Check className="h-3 w-3" /> Accept → plan</Link>
                    </>
                  }
                >
                  {f.recommended_action}
                  <div className="mt-2.5 flex flex-wrap gap-x-3.5 gap-y-1 font-mono text-[10px] text-[var(--p-ink-3)]">
                    {f.citation ? <span style={{ color: "#3f63a0" }}>{f.citation}</span> : null}
                    <span>{f.category}</span>
                    {f.caveat ? <span>caveat: {f.caveat}</span> : null}
                  </div>
                </Exhibit>
              );
            })}

            {/* the trajectory — real multi-year tax (filed solid / projected dashed) */}
            {strategist.trajectory.available && strategist.trajectory.points.length > 1 ? (
              <div className="mt-8">
                <h2><span className="no">III</span>The trajectory</h2>
                {strategist.trajectory.summary ? <p>{strategist.trajectory.summary}</p> : null}
                <div className="mt-3 flex items-end gap-4" style={{ height: 110 }}>
                  {(() => {
                    const pts = strategist.trajectory.points;
                    const max = Math.max(...pts.map((p) => p.total_tax_cents), 1);
                    return pts.map((p, i) => (
                      <div key={p.tax_year} className="flex flex-1 flex-col items-center justify-end gap-1.5">
                        <span className="font-[var(--font-ui)] text-[10.5px] font-bold text-[var(--p-ink)]">{centsToUSD(p.total_tax_cents)}</span>
                        <div
                          className="w-full rounded-t-[3px]"
                          style={{ height: `${(p.total_tax_cents / max) * 80}px`, background: i === 0 ? "var(--p-ink)" : "transparent", border: i === 0 ? "none" : "1.5px dashed var(--p-ink-2)", borderBottom: i === 0 ? "none" : 0 }}
                        />
                        <small className="font-mono text-[9px] text-[var(--p-ink-3)]">{p.tax_year}{i === 0 ? "" : "*"}</small>
                      </div>
                    ));
                  })()}
                </div>
                <p className="fn mt-1">solid = filed · dashed = engine projection</p>
              </div>
            ) : null}

            {/* sign & seal — gold is reserved for exactly this */}
            <div className="mt-9">
              <SignoffBlock
                signed={signed}
                signer={signed ? "you" : undefined}
                date={signed ? `sealed ${strategist.tax_year}` : undefined}
                hash={signed ? "sha256 (additive)" : undefined}
                auditRef={signed ? "persistence: additive" : undefined}
              >
                {!signed ? (
                  <Button variant="seal" onClick={() => setSigned(true)}>✍ Sign &amp; seal</Button>
                ) : null}
              </SignoffBlock>
              {!signed ? (
                <p className="fn mt-2">Signing locks this version and unlocks <i>Accept → plan</i> + the client deliverable. <span className="font-mono text-[10px] text-[var(--p-ink-3)]">[additive] memo persistence + the audit-chain hash land with spec §9.1 — today the seal is local.</span></p>
              ) : (
                <div className="mt-2"><Stamp kind="signed" fresh>signed &amp; sealed</Stamp></div>
              )}
            </div>

            {/* engine notes — every figure, shown working */}
            <div className="mt-8 border-t border-[var(--p-ink)] pt-3.5">
              <MicroLabel>Engine notes — every figure traces to its source</MicroLabel>
              <div className="mt-2 space-y-1">
                {strategist.findings.map((f, i) => (
                  <div key={i} className="flex gap-2.5 py-0.5 text-[12.5px] text-[var(--p-ink-3)]">
                    <span className="cite flex-none font-mono text-[10px] text-[var(--p-seal)]">{exhibitLetter(i)}</span>
                    <span>{f.title} · {f.citation || f.category} → <b className="text-[var(--p-ink-2)]">{centsToUSD(f.estimated_impact_cents)}</b></span>
                  </div>
                ))}
              </div>
              <p className="fn mt-3">{strategist.disclaimer}</p>
            </div>
          </Sheet>
        </div>
      ) : null}

      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist to revise an exhibit…" />
      </div>
    </div>
  );
}
