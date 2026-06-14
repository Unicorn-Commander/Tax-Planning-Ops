"use client";

// Surface 06 — THE MEMORANDUM ★ (frontier). The product: an agent-drafted,
// advisor-curated, engine-footnoted document worth what the firm bills for it.
//
// LIVE: the memo is now PERSISTED + VERSIONED + SIGN/SEAL is real.
//   - GET  /clients/tax-years/{id}/memo            → the memo state (loaded on mount)
//   - POST /clients/tax-years/{id}/strategist/run  → run the strategist, persist a
//                                                    run + ensure a draft memo
//   - PUT  /clients/tax-years/{id}/memo            → save advisor edits to the draft
//   - POST /memos/{id}/sign                        → seal: real content_hash +
//                                                    audit_event_id on the hash-chain
//   - GET  /memos/{id}/redline                     → diff vs the prior signed version
// The findings, savings, prose, and trajectory are real engine output; the
// document Sheet renders them. The gold seal is backed by the audit chain.
//
// [additive] (honestly marked, never faked):
//   - the literal engine-call trace + plan stream (the payload has no call list)
//   - firm branding (GET /admin/branding) — default shown, TODO at the call site
//   - the Technical⟷Client-friendly register transform
// LLM narrates, engines compute — the model cannot invent a figure.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Brain, Pencil, ArrowUpDown, EyeOff, Check, GitCompare } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  Panel, PanelHead, MicroLabel, Annotation, Money, Stamp, Button, MiniButton,
  WorkingDots, Dot, Sheet, Letterhead, SignoffBlock, Exhibit,
  ProvFigure, SourceMark, Omnibar, type Provenance,
} from "@/components/kit";

/* ---- the persisted memo state (GET /clients/tax-years/{id}/memo) ---- */
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
interface StrategistRun {
  id: string;
  findings: Finding[];
  memo_text: string | null;
  current_total_tax_cents: number;
  total_savings_identified_cents: number;
  marginal_rate: string;
  objectives_summary: string | null;
  trajectory: Trajectory;
  disclaimer: string | null;
}
interface MemoOut {
  id: string;
  client_tax_year_id: string;
  strategist_run_id: string | null;
  version: number;
  body_md: string;
  status: "draft" | "signed";
  signed_by: string | null;
  signed_at: string | null;
  content_hash: string | null;
  audit_event_id: string | null;
  supersedes_version: number | null;
  created_at: string;
  updated_at: string;
}
interface MemoVersionSummary {
  version: number;
  status: string;
  signed_at: string | null;
  created_at: string;
}
interface MemoState {
  latest_memo: MemoOut | null;
  versions: MemoVersionSummary[];
  latest_run: StrategistRun | null;
}

// TODO(integration: GET /admin/branding) — firm letterhead; default until it lands
const FIRM_NAME = "Northstar Tax Advisory";
const exhibitLetter = (i: number) => String.fromCharCode(65 + i);
const shortHash = (h: string) => (h.length > 16 ? `${h.slice(0, 16)}…` : h);

export default function MemoPage() {
  const { overview, loading } = useClientOverview();
  const [state, setState] = useState<MemoState | null>(null);
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  // The advisor's working draft body, mirrored locally so the textarea is
  // controlled; seeded from the persisted memo, saved back on blur.
  const [draftBody, setDraftBody] = useState<string>("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);
  const taxYearId = planYear?.id ?? null;

  const run = state?.latest_run ?? null;
  const memo = state?.latest_memo ?? null;
  const isDraft = memo?.status === "draft";
  const isSigned = memo?.status === "signed";

  // Load the memo state on mount (and whenever the tax-year resolves).
  const loadState = useCallback(async () => {
    if (!taxYearId) return;
    const r = await api.get<MemoState>(`/clients/tax-years/${taxYearId}/memo`);
    setState(r.data);
    setDraftBody(r.data.latest_memo?.body_md ?? "");
  }, [taxYearId]);

  const load = useAction(loadState);
  // Fire the initial load once the id is known. (load.run identity is stable
  // for a given taxYearId via useCallback.)
  useEffect(() => {
    if (taxYearId) void load.run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taxYearId]);

  // Run the strategist for real → persists a run + ensures a draft memo.
  const runStrategist = useAction(async () => {
    if (!taxYearId) return;
    const r = await api.post<{ memo_state: MemoState }>(
      `/clients/tax-years/${taxYearId}/strategist/run`,
    );
    setState(r.data.memo_state);
    setDraftBody(r.data.memo_state.latest_memo?.body_md ?? "");
  });

  // Persist the advisor's draft edits (save on blur).
  const saveDraft = useCallback(async () => {
    if (!taxYearId || !memo || memo.status !== "draft") return;
    if (draftBody === memo.body_md) return;
    setSaveState("saving");
    try {
      const r = await api.put<MemoOut>(`/clients/tax-years/${taxYearId}/memo`, {
        body_md: draftBody,
      });
      setState((prev) => (prev ? { ...prev, latest_memo: r.data } : prev));
      setSaveState("saved");
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaveState("idle"), 1800);
    } catch {
      setSaveState("idle");
    }
  }, [taxYearId, memo, draftBody]);

  // Sign & seal → real content_hash + audit_event_id from the audit chain.
  const sign = useAction(async () => {
    if (!memo) return;
    const r = await api.post<MemoOut>(`/memos/${memo.id}/sign`);
    setState((prev) =>
      prev
        ? {
            ...prev,
            latest_memo: r.data,
            versions: prev.versions.map((v) =>
              v.version === r.data.version
                ? { ...v, status: r.data.status, signed_at: r.data.signed_at }
                : v,
            ),
          }
        : prev,
    );
  });

  // Redline vs the prior signed version (only when this draft supersedes one).
  const [redline, setRedline] = useState<{ base_version: number | null; base_body: string | null; new_version: number; new_body: string } | null>(null);
  const [showRedline, setShowRedline] = useState(false);
  const loadRedline = useAction(async () => {
    if (!memo) return;
    const r = await api.get(`/memos/${memo.id}/redline`);
    setRedline(r.data);
    setShowRedline(true);
  });

  useEffect(() => () => { if (savedTimer.current) clearTimeout(savedTimer.current); }, []);

  if (loading || (taxYearId && load.pending && !state)) {
    return <div className="wrap py-7"><div className="skeleton h-[400px] w-full rounded-[14px]" /></div>;
  }
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
  const taxYear = planYear.tax_year;
  const findings = run?.findings ?? [];
  const visibleFindings = findings.filter((_, i) => !hidden.has(i));
  const savingsFindings = visibleFindings.filter((f) => f.impact_kind === "savings");
  // The memo prose: while drafting, show the advisor's working body; once
  // signed it's the sealed body_md. Fall back to the run's narration.
  const memoProse = memo?.body_md ?? run?.memo_text ?? null;
  const supersedesSigned = isDraft && memo?.supersedes_version != null;

  const headlineProv: Provenance | undefined = run ? {
    label: "identified, engine-verified",
    engine: "strategist · engines as tools",
    source: "engine",
    inputs: [
      { k: "findings", v: `${findings.length} (${savingsFindings.length} savings)` },
      { k: "current tax", v: centsToUSD(run.current_total_tax_cents) },
      { k: "marginal", v: `${(Number(run.marginal_rate) * 100).toFixed(1)}%` },
    ],
    auditRef: `tax-year ${taxYearId?.slice(0, 8)}`,
  } : undefined;

  return (
    <div className="wrap py-7 pb-20">
      {/* ===== the run theater ===== */}
      <Panel className="rise">
        <PanelHead>
          <Dot live={runStrategist.pending} />
          <MicroLabel><span className="tone-agent">{runStrategist.pending ? "Running…" : run ? "How this memo was built" : "The strategist drafts the memo"}</span></MicroLabel>
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
                  <span className="fig flex-none text-[var(--g-ink-3)]">{run ? "✓" : i + 1}</span>{s}
                </li>
              ))}
            </ol>
            {runStrategist.pending ? (
              <div className="mt-3 inline-flex items-center gap-2 text-[12px] text-[var(--agent)]"><WorkingDots /> drafting on local inference…</div>
            ) : null}
            {runStrategist.error ? <p className="mt-3 text-[12.5px] text-[var(--cliff)]">{runStrategist.error}</p> : null}
            {load.error ? <p className="mt-3 text-[12.5px] text-[var(--cliff)]">{load.error}</p> : null}
            <div className="mt-3 inline-flex items-center gap-2 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-1.5 font-mono text-[10px] text-[var(--g-ink-3)]">
              <span className="dot" style={{ background: "var(--cost)" }} /> [additive] the literal engine-call trace + the priced-question rail stream with the run payload (spec §9.1).
            </div>
          </div>
          <div className="grid place-items-center p-5">
            {run ? (
              <div className="text-center">
                <Money cents={run.total_savings_identified_cents} tone="save" className="block text-[26px] font-bold" />
                <div className="mt-1 microlabel">identified · {findings.length} findings</div>
                <button
                  className="mini-btn mt-3 inline-flex items-center gap-1"
                  onClick={() => void runStrategist.run()}
                  disabled={runStrategist.pending}
                  title="Re-run the strategist; opens a fresh draft if the memo is already signed"
                >
                  <Brain className="h-3 w-3" /> Re-run
                </button>
              </div>
            ) : (
              <Button variant="ink" icon={<Brain className="h-4 w-4" />} onClick={() => void runStrategist.run()} disabled={runStrategist.pending}>
                {runStrategist.pending ? "Running the strategist…" : "Run the strategist"}
              </Button>
            )}
          </div>
        </div>
      </Panel>

      {/* ===== the document ===== */}
      {run ? (
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
              {client.display_name.split(" ")[0]} · {taxYear}<br />
              {findings.length} findings<br />
              {memo ? <>v{memo.version} · {memo.status}<br /></> : null}
              figures: <span className="text-[var(--agent)]">engine</span> · <span style={{ color: "#3f63a0" }}>doc</span> · <span className="text-[var(--seal)]">books</span>
            </div>
          </nav>

          {/* the sheet */}
          <Sheet className="px-[58px] py-[52px]">
            <Letterhead
              firm={<>{FIRM_NAME} <span className="ml-2 font-[var(--font-ui)] text-[10px] tracking-[0.14em] text-[var(--p-ink-3)]">MEMORANDUM</span></>}
              docRef={`${client.display_name} · ${taxYear}${memo ? ` · v${memo.version}` : ""}`}
            />
            <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-2 text-[13px]">
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Prepared for</div>{client.display_name}</div>
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Prepared by</div>The Strategist · reviewed by you</div>
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Re</div>{taxYear} tax position &amp; planning</div>
              <div><div className="font-[var(--font-ui)] text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--p-ink-3)]">Basis</div>verified return · live books · stated goals</div>
            </div>

            <h1 className="mt-7">{run.objectives_summary ? "Your plan, in one place." : `${taxYear}: where the leverage is.`}</h1>
            {run.objectives_summary ? <p className="lede mt-2">{run.objectives_summary}</p> : null}

            <div className="mt-6 flex items-end gap-6">
              <div>
                <div className="microlabel" style={{ color: "var(--p-ink-3)" }}>identified, engine-verified</div>
                <div className="font-[var(--font-ui)] text-[44px] font-bold leading-none tracking-[-0.03em] text-[var(--p-ink)]">
                  <ProvFigure cents={run.total_savings_identified_cents} prov={headlineProv} tone={undefined} />
                  <SourceMark source="engine" />
                </div>
              </div>
              <p className="max-w-[330px] pb-1.5 text-[13px] text-[var(--p-ink-2)]">
                Across {savingsFindings.length} engine-verified {savingsFindings.length === 1 ? "finding" : "findings"}, ordered below by impact. Current tax {centsToUSD(run.current_total_tax_cents)} at a {(Number(run.marginal_rate) * 100).toFixed(1)}% marginal rate.
              </p>
            </div>

            {/* the memo prose — editable while a draft, sealed once signed */}
            <div className="mt-6">
              <div className="flex items-baseline justify-between">
                <h2 className="!mb-0"><span className="no">I</span>The situation</h2>
                {isDraft ? (
                  <span className="font-mono text-[10px] text-[var(--p-ink-3)]">
                    {saveState === "saving" ? "saving…" : saveState === "saved" ? "saved ✓" : "editable — saves on blur"}
                  </span>
                ) : null}
              </div>
              {isDraft ? (
                <textarea
                  value={draftBody}
                  onChange={(e) => setDraftBody(e.target.value)}
                  onBlur={() => void saveDraft()}
                  spellCheck
                  className="mt-2 block w-full resize-y bg-transparent font-[var(--font-doc)] text-[15px] leading-[1.7] text-[var(--p-ink-2)] outline-none focus:ring-0"
                  style={{ minHeight: 160, border: "1px dashed var(--p-hairline)", borderRadius: 8, padding: "12px 14px" }}
                  placeholder="The strategist's narration — engine numbers, plain words. Edit freely; this saves to the draft."
                />
              ) : memoProse ? (
                memoProse.split(/\n\n+/).slice(0, 12).map((para, i) => (
                  <p key={i}>{para.trim()}</p>
                ))
              ) : null}
            </div>

            {/* findings as curated exhibits */}
            <h2 className="mt-8"><span className="no">II</span>The findings</h2>
            {visibleFindings.length === 0 ? (
              <p className="text-[var(--p-ink-3)]">No findings — the strategist flagged nothing actionable this year.</p>
            ) : null}
            {findings.map((f, i) => {
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
            {run.trajectory.available && run.trajectory.points.length > 1 ? (
              <div className="mt-8">
                <h2><span className="no">III</span>The trajectory</h2>
                {run.trajectory.summary ? <p>{run.trajectory.summary}</p> : null}
                <div className="mt-3 flex items-end gap-4" style={{ height: 110 }}>
                  {(() => {
                    const pts = run.trajectory.points;
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

            {/* sign & seal — gold is reserved for exactly this; now audit-chain backed */}
            <div className="mt-9">
              <SignoffBlock
                signed={isSigned}
                signer={isSigned ? (memo?.signed_by ?? "you") : undefined}
                date={isSigned && memo?.signed_at ? `sealed ${new Date(memo.signed_at).toLocaleDateString()}` : undefined}
                hash={isSigned && memo?.content_hash ? shortHash(memo.content_hash) : undefined}
                auditRef={isSigned && memo?.audit_event_id ? `audit ${memo.audit_event_id.slice(0, 8)}` : undefined}
              >
                {isDraft ? (
                  <Button variant="seal" onClick={() => void sign.run()} disabled={sign.pending}>
                    {sign.pending ? "Sealing…" : "✍ Sign & seal"}
                  </Button>
                ) : null}
              </SignoffBlock>
              {sign.error ? <p className="fn mt-2 text-[var(--cliff)]">{sign.error}</p> : null}
              {isDraft ? (
                <p className="fn mt-2">
                  Signing locks this version and unlocks <i>Accept → plan</i> + the client deliverable. The content hash is appended to the tamper-evident audit chain.
                  {supersedesSigned ? (
                    <>
                      {" "}
                      <button className="underline decoration-dotted" onClick={() => void loadRedline.run()} disabled={loadRedline.pending}>
                        <span className="inline-flex items-center gap-1"><GitCompare className="h-3 w-3" />{loadRedline.pending ? "loading redline…" : `redline vs v${memo?.supersedes_version}`}</span>
                      </button>
                    </>
                  ) : null}
                </p>
              ) : (
                <div className="mt-2 flex items-center gap-3">
                  <Stamp kind="signed" fresh>signed &amp; sealed</Stamp>
                  <button
                    className="mini-btn inline-flex items-center gap-1"
                    onClick={() => void runStrategist.run()}
                    disabled={runStrategist.pending}
                    title="Open a new draft superseding this signed version"
                  >
                    <Pencil className="h-3 w-3" /> Revise (new draft)
                  </button>
                </div>
              )}

              {/* redline panel (vs the prior signed version) */}
              {showRedline && redline ? (
                <div className="mt-3 rounded-[10px] border border-[var(--p-hairline)] p-3.5 text-[12.5px]">
                  <div className="flex items-center justify-between">
                    <MicroLabel>Redline · v{redline.base_version ?? "—"} → v{redline.new_version}</MicroLabel>
                    <button className="mini-btn" onClick={() => setShowRedline(false)}>close</button>
                  </div>
                  <div className="mt-2 grid gap-3 md:grid-cols-2">
                    <div>
                      <div className="microlabel" style={{ color: "var(--p-ink-3)" }}>signed v{redline.base_version ?? "—"}</div>
                      <p className="mt-1 whitespace-pre-wrap font-[var(--font-doc)] text-[var(--p-ink-3)]">{redline.base_body ?? "—"}</p>
                    </div>
                    <div>
                      <div className="microlabel" style={{ color: "var(--p-ink-2)" }}>this draft v{redline.new_version}</div>
                      <p className="mt-1 whitespace-pre-wrap font-[var(--font-doc)] text-[var(--p-ink-2)]">{redline.new_body}</p>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            {/* engine notes — every figure, shown working */}
            <div className="mt-8 border-t border-[var(--p-ink)] pt-3.5">
              <MicroLabel>Engine notes — every figure traces to its source</MicroLabel>
              <div className="mt-2 space-y-1">
                {findings.map((f, i) => (
                  <div key={i} className="flex gap-2.5 py-0.5 text-[12.5px] text-[var(--p-ink-3)]">
                    <span className="cite flex-none font-mono text-[10px] text-[var(--p-seal)]">{exhibitLetter(i)}</span>
                    <span>{f.title} · {f.citation || f.category} → <b className="text-[var(--p-ink-2)]">{centsToUSD(f.estimated_impact_cents)}</b></span>
                  </div>
                ))}
              </div>
              {run.disclaimer ? <p className="fn mt-3">{run.disclaimer}</p> : null}
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
