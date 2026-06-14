// kit/tokens.ts — the design tokens as TypeScript.
//
// The CSS custom properties live in app/globals.css (the source of truth for
// *rendering*). This module mirrors the handful of token VALUES the primitives
// need to *compute* with — strata stops keyed to marginal rate, the per-client
// and per-agent hue assignment, the plain-language gloss map (§0.7), and the
// delta-tone rule (§2). Keep these in sync with globals.css.

/* ---- THE STRATA: ordinary-income marginal rate → its band color ---------- */
// Mirrors --s10…--s37. Used to color a PositionInstrument segment by its rate
// and to look a rate up to its band. Keyed by the statutory bracket rate.
export const STRATA: Record<number, string> = {
  0.1: "var(--s10)",
  0.12: "var(--s12)",
  0.22: "var(--s22)",
  0.24: "var(--s24)",
  0.32: "var(--s32)",
  0.35: "var(--s35)",
  0.37: "var(--s37)",
};
// The LTCG cool ladder (the parallel, cooler lane stacked above ordinary).
export const STRATA_CG: Record<number, string> = {
  0: "var(--cg0)",
  0.15: "var(--cg15)",
  0.2: "var(--cg20)",
};
/** Nearest strata color for an arbitrary marginal rate (0–1). */
export function strataColor(rate: number): string {
  const stops = Object.keys(STRATA).map(Number).sort((a, b) => a - b);
  let best = stops[0];
  for (const s of stops) if (rate >= s) best = s;
  return STRATA[best];
}

/* ---- Semantic tones ------------------------------------------------------ */
export type Tone = "save" | "cost" | "cliff" | "agent" | "seal" | "info";
export const TONE_VAR: Record<Tone, string> = {
  save: "var(--save)",
  cost: "var(--cost)",
  cliff: "var(--cliff)",
  agent: "var(--agent)",
  seal: "var(--seal)",
  info: "var(--info)",
};

/**
 * Delta color = favorable / unfavorable to the CLIENT, never the arithmetic
 * sign (§2). "tax −$14,310" is green; "tax +$2,000" is amber.
 *  - lower-is-better metrics (tax, cost, penalty, premium): a decrease saves.
 *  - higher-is-better metrics (savings, refund, income, benefit): an increase saves.
 */
export type Metric =
  | "tax" | "cost" | "penalty" | "premium" | "rate"      // lower is better
  | "savings" | "refund" | "income" | "benefit" | "keep"; // higher is better
const LOWER_IS_BETTER = new Set<Metric>(["tax", "cost", "penalty", "premium", "rate"]);
export function deltaTone(metric: Metric, signedDelta: number): Tone {
  if (signedDelta === 0) return "info";
  const favorable = LOWER_IS_BETTER.has(metric) ? signedDelta < 0 : signedDelta > 0;
  return favorable ? "save" : "cost";
}

/* ---- Per-client hue (§2): stable hash of id into a curated set ----------- */
// The named demo cast (§8) first, then extra hues so arbitrary clients still
// land on a pleasant, distinct color. Mirrors --chue.
export const CLIENT_HUES = [
  "#56a3a0", // Jordan-teal
  "#5b86a8", // Marcus-steel
  "#b65f72", // Cho-rose
  "#5f9e6e", // Becker-green
  "#9a6fb8", // Nair-violet
  "#c2884f", // Dolores-amber
  "#6f8fb0", // extra-slate
  "#a8804f", // extra-tan
] as const;
/** Stable per-client hue (deterministic hash → CLIENT_HUES). */
export function hueForClient(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return CLIENT_HUES[h % CLIENT_HUES.length];
}

/* ---- Per-agent hue (§2 / §6): the staff -------------------------------- */
export type AgentKey = "strategist" | "clerk" | "bookrunner" | "liaison";
export const AGENT_HUES: Record<AgentKey, string> = {
  strategist: "#11827b", // teal (the lead)
  clerk: "#7fa6c4",      // steel-blue (extractions)
  bookrunner: "#a39a4e", // olive (the book)
  liaison: "#997a31",    // gold (client-facing)
};

/* ---- The plain-language gloss map (§0.7) --------------------------------- */
// The global `what's this?` affordance. Plain, ≤2 sentences, NO statute numbers
// in the gloss itself. Keyed by a slug the surfaces pass to <Term k="...">.
export interface Gloss { term: string; gloss: string }
export const GLOSS: Record<string, Gloss> = {
  "nominal-bracket": {
    term: "Nominal bracket",
    gloss: "The headline rate for your income band — not what your next dollar actually costs.",
  },
  "marginal-rate": {
    term: "True next-dollar rate",
    gloss: "What one more dollar of income would actually be taxed at, once every add-on is counted. The number planning runs on.",
  },
  "effective-rate": {
    term: "Average / effective rate",
    gloss: "Total tax divided by total income — your overall share, lower than your bracket.",
  },
  cliff: {
    term: "Cliff / threshold",
    gloss: "An income line that adds tax the moment you cross it; we show distance + cost of crossing.",
  },
  irmaa: {
    term: "IRMAA",
    gloss: "A Medicare premium surcharge that kicks in above set income lines — and your income two years ago sets it.",
  },
  niit: {
    term: "NIIT",
    gloss: "An extra 3.8% on investment income once income passes $200k single / $250k married.",
  },
  "addl-medicare": {
    term: "Add'l Medicare",
    gloss: "An extra 0.9% on earned income above $200k.",
  },
  qbi: {
    term: "QBI (§199A)",
    gloss: "A 20% deduction on business income; it shrinks past ~$201,750 single / $403,500 married.",
  },
  amt: {
    term: "AMT",
    gloss: "A parallel tax with fewer breaks; you pay it only if it comes out higher than your regular tax.",
  },
  "safe-harbor": {
    term: "Safe harbor",
    gloss: "Pay at least this much during the year (via withholding + estimates) and you owe no underpayment penalty.",
  },
  "roth-conversion": {
    term: "Roth conversion",
    gloss: "Move pre-tax retirement money to Roth now, pay tax now, then it grows and comes out tax-free.",
  },
  qsbs: {
    term: "QSBS (§1202)",
    gloss: "If you hold qualifying small-business C-corp stock 5+ years, a large chunk of the gain can be federally tax-free.",
  },
  "scorp-split": {
    term: "S-corp salary split",
    gloss: "An S-corp owner takes part pay as salary, part as distributions — the split changes payroll tax.",
  },
  bunching: {
    term: "Bunching / DAF",
    gloss: "Stack several years of charitable giving into one year so it clears the standard deduction.",
  },
  "c-corp-1120": {
    term: "C-corp / Form 1120",
    gloss: "A C-corp pays its own 21% federal tax (plus any state); the owner is taxed again on salary and dividends — the double tax.",
  },
  "acc-earnings-tax": {
    term: "Accumulated earnings tax",
    gloss: "A 20% penalty if a C-corp piles up earnings beyond ~$250k without a business reason instead of paying them out.",
  },
  "salary-dividend": {
    term: "Salary vs dividend",
    gloss: "Salary is deductible to the corp but is payroll + ordinary income to the owner; dividends aren't deductible (double-taxed) but skip payroll.",
  },
};

/* ---- Source classes for figures (§0.3) ----------------------------------- */
// engine (teal ∑) · document (blue, opens the page region) · books (gold, AO
// federation). The LLM can never be a source.
export type SourceClass = "engine" | "document" | "books";
