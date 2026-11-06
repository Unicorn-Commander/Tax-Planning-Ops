import assert from "node:assert/strict";
import test from "node:test";
import { normalizeFilingStatus, pickBracketSet } from "./brackets.ts";

const row = { lower_bound_cents: 0, upper_bound_cents: 1240000, rate: "0.1000", ordinal: 1 };

test("normalizes display filing statuses onto the seed keys", () => {
  assert.equal(normalizeFilingStatus("Single"), "single");
  assert.equal(normalizeFilingStatus("married filing jointly"), "mfj");
  assert.equal(normalizeFilingStatus("Head of Household"), "hoh");
});

test("picks the 2026 single federal set and ignores a same-status other year", () => {
  const y2025 = { tax_year: 2025, jurisdiction: "federal", filing_status: "single", rows: [row] };
  const y2026 = { tax_year: "2026", jurisdiction: "Federal", filing_status: "Single", rows: [row] };
  const picked = pickBracketSet([y2025, y2026], 2026, "single");
  assert.equal(picked, y2026);
});

test("returns null when 2026 single is missing instead of borrowing 2025", () => {
  const y2025 = { tax_year: 2025, jurisdiction: "federal", filing_status: "single", rows: [row] };
  assert.equal(pickBracketSet([y2025], 2026, "single"), null);
  assert.equal(pickBracketSet([], 2026, "single"), null);
});

test("rejects a header whose rows did not load", () => {
  const empty = { tax_year: 2026, jurisdiction: "federal", filing_status: "single", rows: [] };
  assert.equal(pickBracketSet([empty], 2026, "single"), null);
});
