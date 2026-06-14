"use client";

// Surface 17 — THE 6-QUESTION INTAKE (the no-return on-ramp)
//
// Reached from /start ("answer 6 questions instead"). Adaptive: questions
// appear only when an engine needs them (owning a business unlocks Q4; no
// business skips to retirement + state). Each question states WHY it matters
// and what it unlocks. Answered questions collapse to editable one-liners;
// the active one is large; a progress bar shows ~N left.
//
// DATA STATUS:
// [live]     — none. This surface is entirely [additive] per the spec (§7-17,
//              §9): the adaptive question graph + the provisional snapshot from
//              rough inputs both require endpoints that DO NOT EXIST yet.
//
// [additive] — the "starting picture" built from rough inputs MUST be clearly
//              labeled as an illustrative estimate (±). It is computed from the
//              locally-typed answers via a rough client-side heuristic (see
//              ROUGH_ESTIMATE below), and is displayed with explicit ± disclaimers.
//              When the real provisional-snapshot endpoint lands it replaces
//              that heuristic entirely. See frontend/INTEGRATION-TODO.17.md.
//
// The questions and their copy are static design content (not API data).
// The interactive question flow itself (useState index + answers) IS real local
// form state — not a mock — but the numbers it produces are illustrative only.

import { useState, useCallback } from "react";
import Link from "next/link";
import { Check, Edit2 } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  MicroLabel,
  Aavatar,
  Button,
  Omnibar,
} from "@/components/kit";

// ---------------------------------------------------------------------------
// The adaptive question graph (static design content, not API data)
// ---------------------------------------------------------------------------

export type AnswerKey = string;

interface Choice {
  key: AnswerKey;
  label: string;
  // what this choice unlocks (shown in the reveal after selection)
  reveal?: string;
  // which follow-up question index to push onto the queue if chosen
  unlocks?: string[];
}

interface Question {
  /** stable id for the adaptive engine to reference */
  id: string;
  /** "Q3 · why it matters" chip */
  why: string;
  /** the main question text */
  text: string;
  /** 1-2 sentence plain-English explanation of why it matters */
  explanation: string;
  choices: Choice[];
  /** if true, this question only appears when unlocked by a prior answer */
  conditional?: boolean;
}

const ALL_QUESTIONS: Question[] = [
  {
    id: "filing-status",
    why: "Changes every bracket and threshold",
    text: "How do you file?",
    explanation:
      "Filing status sets your brackets, standard deduction, and every threshold we check — it is the foundation everything else builds on.",
    choices: [
      { key: "single", label: "Single" },
      { key: "mfj", label: "Married, filing jointly" },
      { key: "mfs", label: "Married, filing separately" },
      { key: "hoh", label: "Head of household" },
    ],
  },
  {
    id: "income",
    why: "Places you on the strata",
    text: "Roughly, what is your total income this year?",
    explanation:
      "We only need a ballpark — within a $50k range is plenty. This places you on the bracket strata and tells us which cliffs and phase-outs are in range.",
    choices: [
      { key: "under100", label: "Under $100k" },
      { key: "100-150", label: "$100k–$150k" },
      { key: "150-250", label: "$150k–$250k" },
      { key: "250-500", label: "$250k–$500k" },
      { key: "over500", label: "Over $500k" },
    ],
  },
  {
    id: "business",
    why: "Opens the biggest levers for most people",
    text: "Do you own a business or have self-employment income?",
    explanation:
      "Business owners have access to salary-split optimization, Solo-401(k), QBI deductions, and entity elections that employees do not. Even a side income matters here.",
    choices: [
      { key: "none", label: "No — just W-2 wages" },
      { key: "sole-prop", label: "Yes — sole proprietor / 1099" },
      {
        key: "scorp-llc",
        label: "Yes — an LLC / S-corp",
        reveal:
          "Good — that means you have an S-corp lever. We’ll check whether your salary is set in the sweet spot.",
        unlocks: ["pay-structure", "retirement"],
      },
      { key: "c-corp", label: "Yes — a C-corp", unlocks: ["retirement"] },
    ],
  },
  {
    id: "pay-structure",
    conditional: true,
    why: "Unlocked because you own an S-corp",
    text: "How does your business pay you?",
    explanation:
      "This is where business owners most often overpay. How you take the money — salary vs. owner draws — changes your tax by thousands, and it’s usually fixable.",
    choices: [
      {
        key: "salary-distrib",
        label: "A salary + owner distributions",
        reveal:
          "Good — that means you have an S-corp lever. We’ll check whether your salary is set in the sweet spot.",
      },
      { key: "draws-only", label: "Just owner draws / profit" },
      { key: "w2", label: "A regular paycheck (W-2)" },
      { key: "unsure", label: "Not sure — explain it" },
    ],
  },
  {
    id: "retirement",
    why: "Often the single largest deduction available",
    text: "Are you contributing to a retirement account?",
    explanation:
      "Pre-tax retirement contributions reduce taxable income dollar-for-dollar and reduce payroll tax too if you’re self-employed. It’s usually the highest-leverage move.",
    choices: [
      {
        key: "none",
        label: "Not yet",
        reveal:
          "There may be significant room here. We’ll size the opportunity.",
      },
      { key: "401k", label: "Yes — a 401(k) or 403(b)" },
      { key: "ira", label: "Yes — an IRA" },
      { key: "self-employed", label: "Yes — a Solo-401(k) or SEP-IRA" },
    ],
  },
  {
    id: "state",
    why: "State tax adds 0–9%+ on top",
    text: "Which state do you live in?",
    explanation:
      "State income tax varies from zero to over 13%. It also affects which strategies are most valuable and the order in which to run them.",
    choices: [
      { key: "no-tax", label: "No state income tax (FL, TX, WA, NV, WY, SD, AK, NH, TN)" },
      { key: "low", label: "Low state tax (under 5%)" },
      { key: "mid", label: "Mid-range (5–8%)" },
      { key: "high", label: "High state tax (CA, NY, HI, NJ — 8%+)" },
    ],
  },
];

// The base question sequence (conditional ones are inserted dynamically)
const BASE_SEQUENCE = ["filing-status", "income", "business", "retirement", "state"];

// ---------------------------------------------------------------------------
// Rough illustrative estimate — CLEARLY LABELED as ±, not an engine figure
// ---------------------------------------------------------------------------
// TODO(integration: POST /agents/provisional-snapshot) — replace this
// client-side heuristic with the real provisional-snapshot endpoint (spec §9,
// additive). When the endpoint exists, call it with the collected answers and
// display its response directly (clearly flagged as provisional until a return
// is imported).

interface RoughEstimate {
  incomeMidCents: number;
  taxMidCents: number;
  bracketLabel: string;
  topOpportunity: string | null;
}

function roughEstimate(answers: Record<string, string>): RoughEstimate {
  const incomeKey = answers["income"];
  const incomeMap: Record<string, [number, string]> = {
    "under100": [65_000_00, "22%"],
    "100-150": [125_000_00, "22%"],
    "150-250": [200_000_00, "24%"],
    "250-500": [375_000_00, "32%"],
    "over500": [650_000_00, "35–37%"],
  };
  const [incomeMidCents, bracketLabel] = incomeMap[incomeKey] ?? [0, "—"];
  // Very rough average-rate approximation — NOT the engine; clearly labeled ±
  const avgRateApprox = incomeKey === "under100" ? 0.12 :
    incomeKey === "100-150" ? 0.17 :
    incomeKey === "150-250" ? 0.20 :
    incomeKey === "250-500" ? 0.23 :
    0.27;
  const taxMidCents = Math.round(incomeMidCents * avgRateApprox);
  const hasBusiness = ["scorp-llc", "sole-prop", "c-corp"].includes(answers["business"] ?? "");
  const noRetirement = answers["retirement"] === "none";
  const topOpportunity =
    answers["pay-structure"] === "salary-distrib" ? "S-corp salary optimization"
    : hasBusiness && noRetirement ? "Solo-401(k) / SEP-IRA contribution"
    : hasBusiness ? "S-corp election / QBI deduction"
    : noRetirement ? "Retirement account contribution"
    : null;
  return { incomeMidCents, taxMidCents, bracketLabel, topOpportunity };
}

function formatCents(cents: number): string {
  if (cents <= 0) return "—";
  const d = cents / 100;
  if (d >= 1_000_000) return `$${(d / 1_000_000).toFixed(1)}M`;
  if (d >= 1_000) return `$${Math.round(d / 1_000)}k`;
  return `$${Math.round(d)}`;
}

// Strata segment widths for the illustrative position bar (proportional to real
// 2025 single-filer bracket dollar spans — static design content, not engine data)
const STRATA_SEGS = [
  { rate: "10%", color: "var(--s10)", flex: 6 },
  { rate: "12%", color: "var(--s12)", flex: 13 },
  { rate: "22%", color: "var(--s22)", flex: 20 },
  { rate: "24%", color: "var(--s24)", flex: 24 },
  { rate: "32%", color: "var(--s32)", flex: 16, dim: true },
  { rate: "35%", color: "var(--s35)", flex: 16, dim: true },
  { rate: "37%", color: "var(--s37)", flex: 5, dim: true },
];

// ---------------------------------------------------------------------------
// Adaptive queue builder
// ---------------------------------------------------------------------------

function buildQueue(answers: Record<string, string>): string[] {
  // Start from base; insert conditional questions when unlocked
  const queue = [...BASE_SEQUENCE];
  const businessAnswer = answers["business"];
  if (businessAnswer === "scorp-llc") {
    // insert pay-structure after business
    const bi = queue.indexOf("business");
    if (!queue.includes("pay-structure")) queue.splice(bi + 1, 0, "pay-structure");
  }
  return queue;
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

export default function IntakePage() {
  // answers: { [questionId]: choiceKey }
  const [answers, setAnswers] = useState<Record<string, string>>({});
  // the question queue (may grow as answers unlock conditional questions)
  const [queue, setQueue] = useState<string[]>(BASE_SEQUENCE);
  // the active question index (index into queue of answered+1)
  const [activeIdx, setActiveIdx] = useState<number>(0);
  // tentative selection for the active question (before "Continue")
  const [tentative, setTentative] = useState<string | null>(null);
  // if we are editing an already-answered question
  const [editingId, setEditingId] = useState<string | null>(null);

  const answeredIds = queue.slice(0, activeIdx);
  const currentId = editingId ?? queue[activeIdx];
  const currentQ = ALL_QUESTIONS.find((q) => q.id === currentId) ?? null;
  const totalExpected = queue.length;
  const answered = activeIdx;
  const remaining = totalExpected - answered;
  const progressPct = totalExpected > 0 ? (answered / totalExpected) * 100 : 0;
  const isDone = activeIdx >= queue.length && !editingId;

  const estimate = roughEstimate(answers);

  const handleChoiceClick = useCallback((key: string) => {
    setTentative(key);
  }, []);

  const handleContinue = useCallback(() => {
    if (!tentative || !currentId) return;
    const newAnswers = { ...answers, [currentId]: tentative };
    setAnswers(newAnswers);

    if (editingId) {
      // rebuild queue in case answer changes unlock/remove a conditional
      const newQueue = buildQueue(newAnswers);
      setQueue(newQueue);
      setEditingId(null);
      setTentative(null);
      return;
    }

    const newQueue = buildQueue(newAnswers);
    setQueue(newQueue);
    setActiveIdx((i) => Math.min(i + 1, newQueue.length));
    setTentative(null);
  }, [tentative, currentId, answers, editingId]);

  const handleSkip = useCallback(() => {
    if (editingId) { setEditingId(null); setTentative(null); return; }
    const newQueue = buildQueue(answers);
    setQueue(newQueue);
    setActiveIdx((i) => Math.min(i + 1, newQueue.length));
    setTentative(null);
  }, [answers, editingId]);

  const handleEdit = useCallback((id: string) => {
    setEditingId(id);
    setTentative(answers[id] ?? null);
  }, [answers]);

  // the selected choice's reveal text (for the active question)
  const selectedChoice = currentQ?.choices.find((c) => c.key === tentative);
  const revealText = selectedChoice?.reveal;

  // Display label for a given answer key in a question
  function answerLabel(qId: string, key: string): string {
    const q = ALL_QUESTIONS.find((q) => q.id === qId);
    return q?.choices.find((c) => c.key === key)?.label ?? key;
  }

  return (
    <div className="mx-auto max-w-[660px] px-5 pb-24 pt-8">

      {/* ---- topbar back link + upload escape hatch ---- */}
      <div className="mb-6 flex items-center justify-between">
        <Link href="/start" className="wordmark text-[13.5px] font-semibold text-[var(--g-ink-2)] hover:text-[var(--g-ink)]">
          <span className="mk" /> <span>&lsaquo; Back</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link
            href="/start"
            className="chip"
          >
            I have my 1040 &rarr; upload instead
          </Link>
          <span className="kbd">⌘K</span>
        </div>
      </div>

      {/* ---- progress bar ---- */}
      {!isDone && (
        <div className="rise mb-5">
          <div className="mb-1.5 flex items-center gap-3">
            <span className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
              {answered} of ~{totalExpected}
            </span>
            <div className="flex-1 h-[5px] rounded-full bg-[var(--wash-2)] overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${progressPct}%`,
                  background: "linear-gradient(90deg, var(--agent), #3fb985)",
                }}
              />
            </div>
            <span className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
              ~{remaining} left
            </span>
          </div>
          <p className="text-[13px] text-[var(--g-ink-3)]">
            No tax return needed. We only ask what changes the answer — and we say why each one matters.
          </p>
        </div>
      )}

      {/* ---- question column ---- */}
      <div className="flex flex-col gap-[14px]">

        {/* answered questions — collapsed + editable */}
        {answeredIds.map((qId, i) => {
          if (editingId === qId) return null; // show as active when editing
          const q = ALL_QUESTIONS.find((q) => q.id === qId);
          if (!q) return null;
          const aKey = answers[qId];
          const aLabel = answerLabel(qId, aKey);
          return (
            <div
              key={qId}
              className={cn(
                "rise flex items-center gap-3 rounded-[12px] border border-[var(--g-hairline-soft)] bg-[var(--g-surface)] px-4 py-3 text-[13.5px]",
                `d${Math.min(i + 1, 6)}`,
              )}
            >
              <span className="flex h-[20px] w-[20px] flex-none items-center justify-center rounded-full bg-[var(--save-soft)] text-[11px] text-[var(--save)]">
                <Check className="h-3 w-3" />
              </span>
              <span className="text-[var(--g-ink-2)]">{q.text}</span>
              <span className="ml-auto font-semibold text-[var(--g-ink)]">{aLabel}</span>
              <button
                type="button"
                onClick={() => handleEdit(qId)}
                className="ml-3 flex items-center gap-1 text-[11.5px] text-[var(--g-ink-3)] hover:text-[var(--agent)] transition-colors"
                aria-label={`Edit answer: ${q.text}`}
              >
                <Edit2 className="h-3 w-3" /> edit
              </button>
            </div>
          );
        })}

        {/* ---- the active (or editing) question ---- */}
        {currentQ && !isDone && (
          <div className="rise d2 rounded-[16px] border border-[var(--g-hairline)] bg-[var(--g-surface)] p-[26px] shadow-[var(--shadow-panel)]">
            <div className="font-mono text-[10.5px] tracking-[0.08em] text-[var(--agent)]">
              {editingId ? "EDITING · " : `QUESTION ${answered + 1} · `}
              {currentQ.why}
            </div>
            <h2 className="mt-2 text-[23px] font-bold leading-tight tracking-[-0.015em]">
              {currentQ.text}
            </h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--g-ink-2)]">
              {currentQ.explanation}
            </p>

            {/* choices */}
            <div className="mt-[18px] grid grid-cols-2 gap-[10px]">
              {currentQ.choices.map((c) => {
                const sel = tentative === c.key;
                return (
                  <button
                    key={c.key}
                    type="button"
                    onClick={() => handleChoiceClick(c.key)}
                    className={cn(
                      "flex items-center gap-[11px] rounded-[12px] border bg-[var(--g-surface)] px-[15px] py-[13px] text-left text-[14px] font-medium transition-[border-color,background]",
                      sel
                        ? "border-[var(--agent)] bg-[var(--agent-soft)]"
                        : "border-[var(--g-hairline)] hover:border-[color-mix(in_srgb,var(--agent)_45%,transparent)] hover:bg-[var(--agent-soft)]",
                    )}
                    aria-pressed={sel}
                  >
                    <span
                      className={cn(
                        "h-[20px] w-[20px] flex-none rounded-full border-[1.5px] transition-[border-color,background,box-shadow]",
                        sel
                          ? "border-[var(--agent)] bg-[var(--agent)] shadow-[inset_0_0_0_3px_var(--g-surface)]"
                          : "border-[var(--g-hairline)]",
                      )}
                    />
                    {c.label}
                  </button>
                );
              })}
            </div>

            {/* reveal text after selection */}
            {revealText && (
              <div className="mt-3 rounded-r-[8px] border-l-2 border-[color-mix(in_srgb,var(--agent)_45%,transparent)] bg-[var(--agent-soft)] px-[14px] py-[11px] text-[12.5px] text-[var(--g-ink-2)]">
                <span className="font-semibold text-[var(--agent)]">Good.</span>{" "}
                {revealText}
              </div>
            )}

            {/* nav */}
            <div className="mt-5 flex items-center gap-[10px]">
              <Button
                variant="ink"
                onClick={handleContinue}
                disabled={!tentative}
              >
                {editingId ? "Save change" : "Continue →"}
              </Button>
              <button
                type="button"
                onClick={handleSkip}
                className="ml-auto text-[12.5px] text-[var(--g-ink-3)] hover:text-[var(--g-ink-2)] transition-colors"
              >
                {editingId ? "Cancel" : "I don’t know — skip for now"}
              </button>
            </div>
          </div>
        )}

        {/* ---- done state ---- */}
        {isDone && (
          <div className="rise d2 rounded-[16px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-7 py-8 shadow-[var(--shadow-panel)] text-center">
            <span className="mx-auto mb-3 flex h-[40px] w-[40px] items-center justify-center rounded-full bg-[var(--save-soft)] text-[var(--save)]">
              <Check className="h-5 w-5" />
            </span>
            <h2 className="text-[20px] font-bold tracking-[-0.015em]">That&apos;s everything we need for now.</h2>
            <p className="mt-1.5 text-[13.5px] text-[var(--g-ink-2)]">
              Your rough starting picture is below. When you add your real return, every number becomes exact.
            </p>
            <div className="mt-5 flex justify-center gap-3">
              <Link href="/start" className="btn btn-ink">
                Go to my plan &rarr;
              </Link>
              <Link href="/start" className="btn btn-ghost">
                Add my 1040 for exact numbers
              </Link>
            </div>
          </div>
        )}

        {/* ---- the live "starting picture" (illustrative ±, NOT engine output) ---- */}
        {(answered >= 2 || isDone) && (
          <section className="rise d3 rounded-[14px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-[18px] py-[16px]">
            <div className="mb-[10px] flex items-center gap-[9px]">
              <Aavatar name="S" agent="strategist" className="!h-[26px] !w-[26px] !text-[10px]" />
              <MicroLabel>Your starting picture &middot; filling in as you answer</MicroLabel>
              {/* ILLUSTRATIVE LABEL — non-negotiable per Honesty Protocol */}
              <span className="ml-auto rounded-[5px] border border-[var(--g-hairline-soft)] bg-[var(--wash-2)] px-2 py-0.5 font-mono text-[9.5px] text-[var(--g-ink-3)]">
                ± illustrative
              </span>
            </div>

            {/* income row */}
            {answers["income"] && (
              <div className="flex items-baseline justify-between py-1 text-[12.5px] text-[var(--g-ink-2)]">
                <span>Estimated income</span>
                <span className="font-mono font-semibold text-[var(--g-ink)]">
                  ~{formatCents(estimate.incomeMidCents)}
                  <span className="ml-1 font-normal text-[var(--g-ink-3)]">(±, midpoint of your range)</span>
                </span>
              </div>
            )}

            {/* tax row */}
            {answers["income"] && (
              <div className="flex items-baseline justify-between py-1 text-[12.5px] text-[var(--g-ink-2)]">
                <span>Estimated federal tax</span>
                <span className="font-mono font-semibold text-[var(--g-ink)]">
                  ~{formatCents(estimate.taxMidCents)}
                  <span className="ml-1 font-normal text-[var(--g-ink-3)]">(±, until we see the return)</span>
                </span>
              </div>
            )}

            {/* bracket row — pending until income answered */}
            <div className="flex items-baseline justify-between py-1 text-[12.5px]">
              <span className="text-[var(--g-ink-2)]">Your bracket</span>
              {answers["income"] ? (
                <span className="font-mono font-semibold text-[var(--g-ink)]">
                  ~{estimate.bracketLabel} top rate
                  <span className="ml-1 font-normal text-[var(--g-ink-3)]">(±)</span>
                </span>
              ) : (
                <span className="font-mono text-[var(--g-ink-3)]">building&hellip;</span>
              )}
            </div>

            {/* illustrative strata bar — static design proportions, not engine spans */}
            {answers["income"] && (
              <div className="relative mt-2 mb-1">
                <div className="flex h-[22px] gap-[2px] overflow-hidden rounded-[6px]">
                  {STRATA_SEGS.map((seg) => (
                    <div
                      key={seg.rate}
                      className="h-full"
                      style={{
                        flex: seg.flex,
                        background: seg.color,
                        opacity: seg.dim ? 0.18 : 0.75,
                      }}
                      title={seg.rate}
                    />
                  ))}
                </div>
                {/* "you" marker — rough midpoint based on income range */}
                <span
                  className="absolute top-[-4px] bottom-[-4px] w-[2px] bg-[var(--g-ink)]"
                  style={{
                    left: `${
                      answers["income"] === "under100" ? 30
                      : answers["income"] === "100-150" ? 40
                      : answers["income"] === "150-250" ? 50
                      : answers["income"] === "250-500" ? 62
                      : 75
                    }%`,
                  }}
                  aria-label="Your estimated position"
                />
              </div>
            )}

            <p className="mt-1.5 font-mono text-[9.5px] text-[var(--g-ink-3)]">
              Strata widths are proportional to 2025 single-filer bracket spans (illustrative — not adjusted for filing status until a return is loaded).
            </p>

            {/* opportunity row */}
            {estimate.topOpportunity && (
              <div className="mt-2 flex items-baseline justify-between py-1 text-[12.5px]">
                <span className="text-[var(--save)]">Already spotted</span>
                <span className="font-semibold text-[var(--save)]">
                  1 likely opportunity &mdash; {estimate.topOpportunity}
                </span>
              </div>
            )}

            {/* honesty note — per IMPLEMENTATION-BRIEF §1 Honesty Protocol */}
            <div className="mt-2 rounded-[6px] border border-dashed border-[var(--g-hairline-soft)] bg-[var(--g-surface)] px-3 py-2 font-mono text-[9.5px] text-[var(--g-ink-3)]">
              {/* TODO(integration: POST /agents/provisional-snapshot) */}
              <span className="text-[var(--cost)]">[additive]</span> These figures are rough client-side estimates (±), not engine output.
              The provisional snapshot from rough inputs lands with the{" "}
              <code>POST /agents/provisional-snapshot</code> endpoint (spec §9, additive).
              See <code>INTEGRATION-TODO.17.md</code>.
            </div>
          </section>
        )}

        {/* ---- closer: always ends pointing back to the real-return path ---- */}
        <div className="rise d4 mt-2 text-center text-[12.5px] leading-relaxed text-[var(--g-ink-3)]">
          <span className="font-semibold text-[var(--g-ink-2)]">This gets you a rough plan in about a minute.</span>{" "}
          When you&apos;re ready, drop your real 1040 and every number becomes exact &mdash; to the dollar.
          <br />
          <Link
            href="/start"
            className="mt-1 inline-block font-semibold text-[var(--agent)] hover:underline"
          >
            Skip ahead with what I&apos;ve got &rarr;
          </Link>
        </div>
      </div>

      {/* ---- omnibar ---- */}
      <div className="mt-8">
        <Omnibar placeholder="Ask about any of these questions…" />
      </div>
    </div>
  );
}
