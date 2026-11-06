// Pick the federal ordinary-income bracket set for a plan year and filing
// status. Suite seeds use jurisdiction "federal" and status keys single / mfj /
// mfs / hoh / qss (IRS Rev. Proc. 2024-40 for 2025, Rev. Proc. 2025-32 for
// 2026). Match the year exactly: painting another year's strata under a 2026
// plan is how the position chart used to look "loaded" while being wrong.

export interface BracketRowLike {
  lower_bound_cents: number;
  upper_bound_cents: number | null;
  rate: string | number;
  ordinal?: number;
}

export interface BracketSetLike {
  tax_year: number | string;
  jurisdiction?: string | null;
  filing_status: string;
  rows?: BracketRowLike[] | null;
}

const FILING_ALIASES: Record<string, string> = {
  single: "single",
  s: "single",
  mfj: "mfj",
  marriedfilingjointly: "mfj",
  married_filing_jointly: "mfj",
  mfs: "mfs",
  marriedfilingseparately: "mfs",
  hoh: "hoh",
  headofhousehold: "hoh",
  qss: "qss",
  qualifyingsurvivingspouse: "qss",
  widow: "qss",
};

export function normalizeFilingStatus(raw: string | null | undefined): string {
  const compact = (raw ?? "").trim().toLowerCase().replace(/[\s-]+/g, "");
  return FILING_ALIASES[compact] ?? compact;
}

/** The set whose year, federal jurisdiction, and filing status match, with rows. */
export function pickBracketSet<T extends BracketSetLike>(
  sets: readonly T[] | null | undefined,
  year: number | string,
  filingStatus: string,
): T | null {
  if (!sets?.length) return null;
  const yearN = Number(year);
  const status = normalizeFilingStatus(filingStatus);
  if (!Number.isFinite(yearN) || !status) return null;
  const federal = sets.filter((set) => (set.jurisdiction ?? "").toLowerCase().includes("fed"));
  const pool = federal.length ? federal : sets;
  return (
    pool.find(
      (set) =>
        Number(set.tax_year) === yearN &&
        normalizeFilingStatus(set.filing_status) === status &&
        (set.rows?.length ?? 0) > 0,
    ) ?? null
  );
}
