"use client";

// Surface 00 — THE CONSOLE (door 2). The shell is real (it IS the door); the MCP
// server (door 3) is LIVE (a real stdio MCP server, 31 tools, manifest 0.2.0);
// and the streaming run is now LIVE too: "Run the strategist" opens a real
// Server-Sent-Events stream off
//   POST /agents/clients/tax-years/:id/strategist/stream
// and renders, live, the plan card (each step running→done), the literal
// engine-call feed (the same deterministic optimizers the GUI buttons call) with
// their summaries, each finding as it lands, then the authored memo, ending on
// the real totals. Every dollar is engine-computed server-side — the stream only
// narrates progress; nothing is faked client-side (the AO port's mistake).
//
// HONESTY — what's live vs still genuinely pending:
// [live] the streaming run (plan + engine-call trace + findings + memo + totals).
// [live] the MCP server (door 3).
// [additive] inline-artifact "open in full" deep-links, GUI↔chat edit-sync, and
//   priced-question objects (the backend streams findings, not interactive priced
//   questions) — all honestly labeled, not faked.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { getStoredWorkspaceId, WORKSPACE_HEADER_NAME } from "@/lib/workspace";
import {
  ConsolePane,
  ConsoleMessage,
  EngineCallRow,
  DoorsMini,
  Aavatar,
  Chip,
  Panel,
  PanelHead,
  MicroLabel,
  Money,
  Stamp,
  WorkingDots,
} from "@/components/kit";

/* ===================== the live SSE event contract ===================== *
 * Mirrors backend app/services/strategist_stream.py exactly. Discriminated on
 * `type` so dispatch is exhaustive and no figure is ever invented client-side. */
interface PlanStep {
  key: string;
  label: string;
}
interface Finding {
  title: string;
  category: string;
  recommended_action: string;
  estimated_impact_cents: number;
  impact_kind: "savings" | "cost" | "info" | string;
  citation: string;
  caveat: string;
}
type StrategistEvent =
  | { type: "plan"; steps: PlanStep[] }
  | { type: "engine_call"; name: string; status: "running" }
  | { type: "engine_call"; name: string; status: "done"; summary: string }
  | { type: "finding"; finding: Finding }
  | { type: "memo"; text: string }
  | { type: "done"; current_total_tax_cents: number; total_savings_identified_cents: number };

/* ---- minimal client/overview shapes (same fields the file surfaces read) ---- */
interface ClientRow {
  id: string;
  display_name: string;
  filing_status_default?: string;
  primary_state?: string | null;
}
interface OverviewYearResolution {
  plan_year_id: string | null;
  base_year_id: string | null;
}

const EXAMPLES = [
  "What's my true next-dollar rate?",
  "/scan-book",
  "Draft the memo for Marcus Webb",
  "Compare an S-corp split at $45k vs $60k salary",
];

/** The API base the axios client uses ( …/api/v1 ). The shared client can't
 *  stream, so we fetch() the SSE endpoint directly but reuse the same base +
 *  the same auth (Bearer access_token + the workspace header). */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

/**
 * Open the strategist SSE stream over POST and dispatch each event.
 *
 * Browser EventSource is GET-only and can't set Authorization, so we use
 * fetch() + response.body.getReader(): POST with the auth + workspace headers,
 * read the body as it arrives, split on the SSE frame boundary ("\n\n"), strip
 * the "data: " prefix, JSON.parse, and hand each event to `onEvent`. The caller
 * passes an AbortSignal so the read is torn down cleanly on unmount / re-run.
 *
 * Returns nothing on success; throws on a non-OK response or a transport error
 * (the caller surfaces that as the run's error state). An AbortError from the
 * signal is swallowed (an intentional cancel is not a failure).
 */
async function consumeStrategistStream(
  taxYearId: string,
  onEvent: (event: StrategistEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const workspaceId = getStoredWorkspaceId();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (workspaceId) headers[WORKSPACE_HEADER_NAME] = workspaceId;

  let res: Response;
  try {
    res = await fetch(
      `${API_BASE_URL}/agents/clients/tax-years/${taxYearId}/strategist/stream`,
      { method: "POST", headers, body: "{}", signal },
    );
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    throw err;
  }

  if (!res.ok || !res.body) {
    // The endpoint maps a missing year/snapshot/bracket set to a 404 BEFORE the
    // stream opens, so a non-OK status here is a real, surfaceable failure.
    throw new Error(`stream failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatchFrame = (frame: string) => {
    // An SSE frame may carry multiple "data:" lines; the backend emits one per
    // frame, but parse defensively and ignore comments/blank lines.
    for (const rawLine of frame.split("\n")) {
      const line = rawLine.trimEnd();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload) as StrategistEvent);
      } catch {
        // A partial/garbled frame: skip it rather than break the whole run.
      }
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        if (frame.trim()) dispatchFrame(frame);
      }
    }
    // Flush any trailing frame the server didn't terminate with a blank line.
    buffer += decoder.decode();
    if (buffer.trim()) dispatchFrame(buffer);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    throw err;
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* already released */
    }
  }
}

/* ===================== the run's live state ===================== */
type StepStatus = "pending" | "running" | "done";
interface PlanRow {
  key: string;
  label: string;
  status: StepStatus;
  summary?: string;
}
interface RunState {
  plan: PlanRow[];
  /** the literal engine-call feed, in arrival order (running rows fill in done) */
  calls: { name: string; running: boolean; summary?: string }[];
  findings: Finding[];
  memo: string | null;
  totals: { current_total_tax_cents: number; total_savings_identified_cents: number } | null;
  streaming: boolean;
  error: string | null;
}
const EMPTY_RUN: RunState = {
  plan: [],
  calls: [],
  findings: [],
  memo: null,
  totals: null,
  streaming: false,
  error: null,
};

function reduceEvent(prev: RunState, ev: StrategistEvent): RunState {
  switch (ev.type) {
    case "plan":
      return {
        ...prev,
        plan: ev.steps.map((s) => ({ key: s.key, label: s.label, status: "pending" as StepStatus })),
      };
    case "engine_call": {
      // Mark the matching plan step, and append/close the literal call feed row.
      const plan = prev.plan.map((p) =>
        p.key === ev.name
          ? {
              ...p,
              status: (ev.status === "done" ? "done" : "running") as StepStatus,
              summary: ev.status === "done" ? ev.summary : p.summary,
            }
          : p,
      );
      let calls = prev.calls;
      if (ev.status === "running") {
        calls = [...prev.calls, { name: ev.name, running: true }];
      } else {
        // close the most recent open row for this name
        let closed = false;
        calls = [...prev.calls]
          .reverse()
          .map((c) => {
            if (!closed && c.name === ev.name && c.running) {
              closed = true;
              return { ...c, running: false, summary: ev.summary };
            }
            return c;
          })
          .reverse();
        if (!closed) calls = [...prev.calls, { name: ev.name, running: false, summary: ev.summary }];
      }
      return { ...prev, plan, calls };
    }
    case "finding":
      return { ...prev, findings: [...prev.findings, ev.finding] };
    case "memo":
      return { ...prev, memo: ev.text };
    case "done":
      return {
        ...prev,
        plan: prev.plan.map((p) => (p.status === "done" ? p : { ...p, status: "done" as StepStatus })),
        totals: {
          current_total_tax_cents: ev.current_total_tax_cents,
          total_savings_identified_cents: ev.total_savings_identified_cents,
        },
        streaming: false,
      };
    default:
      return prev;
  }
}

/* Human label for an engine-call name (the stream's stable step keys). */
const CALL_LABELS: Record<string, string> = {
  comprehensive_return: "comprehensive_return",
  roth_optimizer: "optimize_roth_conversion",
  scorp_optimizer: "optimize_scorp_salary",
  opportunity_scan: "find_opportunities",
  irmaa_check: "calculate_irmaa",
  goal_aware: "goal_aware_findings",
  author_memo: "author_memo",
};

function ConsoleInner() {
  const params = useSearchParams();
  const seeded = params.get("q");

  // ---- conversation log (the left pane) ----
  const [log, setLog] = useState<{ from: "you" | "them"; text: string }[]>([]);

  // ---- client / tax-year picker (the run needs a tax_year_id) ----
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const [taxYearId, setTaxYearId] = useState<string | null>(null);
  const [resolvingYear, setResolvingYear] = useState(false);

  // ---- the live strategist run ----
  const [run, setRun] = useState<RunState>(EMPTY_RUN);
  const abortRef = useRef<AbortController | null>(null);

  // Abort any in-flight stream when the component unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (seeded) setLog([{ from: "you", text: seeded }, RUN_HINT_REPLY]);
  }, [seeded]);

  // [live] GET /clients — the picker the run targets.
  useEffect(() => {
    api
      .get("/clients")
      .then((r) => {
        const list: ClientRow[] = Array.isArray(r.data) ? r.data : (r.data?.clients ?? []);
        setClients(list);
        setSelectedClientId((cur) => cur ?? list[0]?.id ?? null);
      })
      .catch(() => setClients([]));
  }, []);

  // [live] GET /clients/:id/overview → resolve plan_year_id ?? base_year_id
  // (the same tax-year resolution the file surfaces use).
  useEffect(() => {
    if (!selectedClientId) {
      setTaxYearId(null);
      return;
    }
    let cancelled = false;
    setResolvingYear(true);
    setTaxYearId(null);
    api
      .get<OverviewYearResolution>(`/clients/${selectedClientId}/overview`)
      .then((r) => {
        if (cancelled) return;
        setTaxYearId(r.data.plan_year_id ?? r.data.base_year_id ?? null);
      })
      .catch(() => {
        if (!cancelled) setTaxYearId(null);
      })
      .finally(() => {
        if (!cancelled) setResolvingYear(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedClientId]);

  function send(v: string) {
    setLog((l) => [...l, { from: "you", text: v }, RUN_HINT_REPLY]);
  }

  // ---- open the real stream ----
  const runStrategist = useCallback(() => {
    if (!taxYearId || run.streaming) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRun({ ...EMPTY_RUN, streaming: true });
    consumeStrategistStream(
      taxYearId,
      (ev) => setRun((prev) => reduceEvent(prev, ev)),
      controller.signal,
    )
      .then(() => {
        // If the stream ended without a terminal `done`, stop the indicator.
        setRun((prev) => (prev.streaming ? { ...prev, streaming: false } : prev));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setRun((prev) => ({
          ...prev,
          streaming: false,
          error: err instanceof Error ? err.message : "the strategist stream failed",
        }));
      });
  }, [taxYearId, run.streaming]);

  const stopStrategist = useCallback(() => {
    abortRef.current?.abort();
    setRun((prev) => ({ ...prev, streaming: false }));
  }, []);

  const selectedClient = useMemo(
    () => clients?.find((c) => c.id === selectedClientId) ?? null,
    [clients, selectedClientId],
  );
  const hasRun = run.plan.length > 0 || run.calls.length > 0 || run.findings.length > 0 || run.memo !== null;
  const canRun = !!taxYearId && !run.streaming;

  return (
    <div className="wrap grid gap-5 py-7 lg:grid-cols-[1.4fr_1fr]">
      {/* ====================== left: the conversation ====================== */}
      <ConsolePane
        className="h-[72vh]"
        head={
          <>
            <Aavatar name="Strategist" agent="strategist" />
            <div className="leading-tight">
              <div className="text-[14px] font-semibold">Strategist</div>
              <div className="font-mono text-[11px] text-[var(--g-ink-3)]">propose · you sign</div>
            </div>
            <div className="ml-auto">
              <DoorsMini active="console" />
            </div>
          </>
        }
        onSubmit={send}
      >
        {log.length === 0 ? (
          <ConsoleMessage from="them" avatar={<Aavatar name="Strategist" agent="strategist" />}>
            I work the file; you sign the memo. Ask me anything, run a command — the same engine
            tools the buttons call — or <b>run the strategist</b> on a client to watch the plan,
            the literal engine calls, the findings, and the memo land live. Try one:
            <div className="mt-2.5 flex flex-wrap gap-2">
              {EXAMPLES.map((e) => (
                <Chip key={e} tone="agent" onClick={() => send(e)}>{e}</Chip>
              ))}
            </div>
          </ConsoleMessage>
        ) : (
          log.map((m, i) =>
            m.from === "you" ? (
              <ConsoleMessage key={i} from="you">{m.text}</ConsoleMessage>
            ) : (
              <ConsoleMessage key={i} from="them" avatar={<Aavatar name="Strategist" agent="strategist" />}>
                {m.text}
              </ConsoleMessage>
            ),
          )
        )}
      </ConsolePane>

      {/* ====================== right: the canvas (the live run) ====================== */}
      <div className="flex flex-col gap-4">
        {/* run control: pick a client → resolve its tax year → open the stream */}
        <Panel className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            <MicroLabel>Run the strategist</MicroLabel>
            <div className="ml-auto flex items-center gap-2">
              <label className="sr-only" htmlFor="console-client">Client</label>
              <select
                id="console-client"
                className="rounded-[8px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-2.5 py-1.5 text-[12.5px] text-[var(--g-ink)] outline-none"
                value={selectedClientId ?? ""}
                onChange={(e) => setSelectedClientId(e.target.value || null)}
                disabled={!clients || clients.length === 0 || run.streaming}
              >
                {clients === null ? (
                  <option value="">loading clients…</option>
                ) : clients.length === 0 ? (
                  <option value="">no clients</option>
                ) : (
                  clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.display_name}</option>
                  ))
                )}
              </select>
              {run.streaming ? (
                <button type="button" className="mini-btn" onClick={stopStrategist}>Stop</button>
              ) : (
                <button
                  type="button"
                  className="mini-btn go"
                  onClick={runStrategist}
                  disabled={!canRun}
                  title={!taxYearId ? "No confirmed tax year for this client yet" : undefined}
                >
                  Run the strategist
                </button>
              )}
            </div>
          </div>
          <p className="mt-2 font-mono text-[10.5px] text-[var(--g-ink-3)]">
            {run.streaming ? (
              <span className="tone-agent">● streaming<WorkingDots className="ml-1" /></span>
            ) : resolvingYear ? (
              <>resolving the tax year…</>
            ) : selectedClient && taxYearId ? (
              <>targets <b className="text-[var(--g-ink-2)]">{selectedClient.display_name}</b> · POST /agents/clients/tax-years/<span className="text-[var(--g-ink-2)]">{taxYearId.slice(0, 8)}…</span>/strategist/stream</>
            ) : selectedClient ? (
              <>no confirmed tax year for {selectedClient.display_name} — import &amp; confirm a return first</>
            ) : (
              <>pick a client to run against</>
            )}
          </p>
          {run.error ? (
            <p className="mt-2 rounded-[8px] border border-[color-mix(in_srgb,var(--cost)_40%,transparent)] bg-[var(--cost-soft)] px-3 py-2 text-[12px] tone-cost">
              Couldn&rsquo;t run the strategist — {run.error}. The figures only ever come from the
              engine; nothing partial is shown as a result.
            </p>
          ) : null}
        </Panel>

        {/* the run-theater: plan → engine-call feed → findings → memo → totals */}
        {!hasRun && !run.streaming ? (
          <Panel className="h-fit p-5">
            <MicroLabel>the canvas</MicroLabel>
            <p className="mt-2 text-[13.5px] text-[var(--g-ink-2)]">
              The right pane is the workspace the Console acts on. Run the strategist above and it
              fills here, live: the <b>plan</b>, the <b>literal engine calls</b> (the same
              deterministic optimizers the GUI buttons call) with their summaries, each <b>finding</b>{" "}
              as it lands, then the authored <b>memo</b> — ending on the real totals. Every dollar is
              engine-computed server-side.
            </p>
            <ul className="mt-3 space-y-1.5 text-[12.5px] text-[var(--g-ink-3)]">
              <li><b className="tone-agent">[live]</b> strategist / propose-plan / scan-book are the answer engine.</li>
              <li><b className="tone-agent">[live]</b> the streaming run — plan, call trace, findings, and memo over <code>POST …/strategist/stream</code>.</li>
              <li><b className="tone-agent">[live]</b> the MCP server (door 3) — a real stdio server, 31 tools, manifest 0.2.0, Brigade-discoverable.</li>
              <li><b className="tone-cost">[additive]</b> inline-artifact &quot;open in full&quot; deep-links, GUI↔chat edit-sync, and priced-question objects (the stream lands findings, not interactive priced questions).</li>
            </ul>
          </Panel>
        ) : (
          <>
            {/* ---- the plan card (steps marked running→done as calls arrive) ---- */}
            {run.plan.length > 0 ? (
              <Panel>
                <PanelHead>
                  <MicroLabel>the plan</MicroLabel>
                  <span className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]">
                    {run.plan.filter((p) => p.status === "done").length}/{run.plan.length} steps
                  </span>
                </PanelHead>
                <ol className="m-0 list-none p-2">
                  {run.plan.map((s, i) => (
                    <li key={s.key} className="flex items-center gap-3 px-3 py-1.5 text-[13px]">
                      <span className="fig flex-none w-4 text-[var(--g-ink-3)]">{i + 1}</span>
                      <span className={s.status === "pending" ? "text-[var(--g-ink-3)]" : "text-[var(--g-ink)]"}>
                        {s.label}
                      </span>
                      <span className="ml-auto font-mono text-[10px]">
                        {s.status === "running" ? (
                          <span className="tone-agent">running<WorkingDots className="ml-1" /></span>
                        ) : s.status === "done" ? (
                          <span className="tone-save">done ✓</span>
                        ) : (
                          <span className="text-[var(--g-ink-3)]">queued</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ol>
              </Panel>
            ) : run.streaming ? (
              <Panel className="p-5">
                <span className="font-mono text-[11px] text-[var(--g-ink-3)]">
                  opening the stream<WorkingDots className="ml-1" />
                </span>
              </Panel>
            ) : null}

            {/* ---- the literal engine-call feed (the real tool calls + summaries) ---- */}
            {run.calls.length > 0 ? (
              <Panel className="p-4">
                <MicroLabel>the engine calls</MicroLabel>
                <div className="mt-2.5 space-y-1.5">
                  {run.calls.map((c, i) => (
                    <EngineCallRow
                      key={`${c.name}-${i}`}
                      tool={CALL_LABELS[c.name] ?? c.name}
                      running={c.running}
                      ok={!c.running}
                      result={c.summary}
                    />
                  ))}
                </div>
              </Panel>
            ) : null}

            {/* ---- findings as they land (engine impact figures, never recomputed here) ---- */}
            {run.findings.length > 0 ? (
              <Panel>
                <PanelHead>
                  <MicroLabel>findings</MicroLabel>
                  <span className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]">{run.findings.length}</span>
                </PanelHead>
                <div>
                  {run.findings.map((f, i) => {
                    const tone = f.impact_kind === "savings" ? "save" : f.impact_kind === "cost" ? "cost" : "neutral";
                    return (
                      <div key={i} className="border-t border-[var(--g-hairline-soft)] px-4 py-3 first:border-t-0">
                        <div className="flex items-start gap-3">
                          <div className="min-w-0">
                            <div className="text-[13.5px] font-semibold tracking-[-0.01em]">{f.title}</div>
                            <p className="mt-0.5 text-[12.5px] text-[var(--g-ink-2)]">{f.recommended_action}</p>
                          </div>
                          {f.estimated_impact_cents ? (
                            <Money cents={f.estimated_impact_cents} tone={tone === "save" ? "save" : tone === "cost" ? "cost" : undefined} className="ml-auto flex-none text-[14px] font-bold" />
                          ) : null}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[10px] text-[var(--g-ink-3)]">
                          <span className="rounded-[6px] bg-[var(--wash)] px-1.5 py-0.5">{f.category}</span>
                          <span>{f.impact_kind}</span>
                          {f.citation ? <span>· {f.citation}</span> : null}
                          {f.caveat ? <span className="not-italic">· {f.caveat}</span> : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Panel>
            ) : null}

            {/* ---- the authored memo (arrives whole — the LLM client doesn't token-stream) ---- */}
            {run.memo ? (
              <Panel className="p-5">
                <div className="flex items-center gap-2">
                  <MicroLabel>the memo</MicroLabel>
                  <Stamp kind="draft" className="ml-auto !transform-none !text-[9px]">authored</Stamp>
                </div>
                <div className="mt-2.5 whitespace-pre-wrap text-[13.5px] leading-[1.55] text-[var(--g-ink)]">
                  {run.memo}
                </div>
                <div className="mt-3 border-t border-[var(--g-hairline-soft)] pt-2.5">
                  {selectedClientId ? (
                    <Link href={`/c/${selectedClientId}/memo`} className="chip">Open the memo surface →</Link>
                  ) : null}
                </div>
              </Panel>
            ) : null}

            {/* ---- terminal totals (the run's bottom line) ---- */}
            {run.totals ? (
              <Panel className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
                <div>
                  <MicroLabel>current total tax</MicroLabel>
                  <div className="mt-0.5"><Money cents={run.totals.current_total_tax_cents} className="text-[18px] font-bold" /></div>
                </div>
                <div>
                  <MicroLabel><span className="tone-save">savings identified</span></MicroLabel>
                  <div className="mt-0.5"><Money cents={run.totals.total_savings_identified_cents} tone="save" className="text-[18px] font-bold" /></div>
                </div>
                <Stamp kind="verified" className="ml-auto !transform-none">engine-computed</Stamp>
              </Panel>
            ) : null}

            {/* honesty footer — what's still genuinely pending */}
            <div className="rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2 font-mono text-[10px] text-[var(--g-ink-3)]">
              <span className="tone-agent">[live]</span> plan · the literal engine-call feed · findings · the authored memo · the totals — all real engine output streamed over{" "}
              <code>POST /agents/clients/tax-years/:id/strategist/stream</code>.{" "}
              <span className="tone-cost">[additive]</span> inline-artifact &quot;open in full&quot; deep-links, GUI↔chat edit-sync, and priced-question objects (the stream lands findings, not interactive priced questions).
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const RUN_HINT_REPLY = {
  from: "them" as const,
  text:
    "Heard. To watch me actually work — my plan, the literal engine calls, each finding, then the memo — pick a client on the right and hit Run the strategist. It streams the real engine output; I won't fake a figure here.",
};

export default function ConsolePage() {
  return (
    <Suspense fallback={<div className="wrap py-7"><div className="skeleton h-[60vh] w-full" /></div>}>
      <ConsoleInner />
    </Suspense>
  );
}
