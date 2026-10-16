import assert from "node:assert/strict";
import test from "node:test";
import { businessDate, currentBusinessQuarter, formatDateOnly } from "./time.ts";

test("keeps a date-only deadline on its calendar date in an Eastern browser", () => {
  assert.equal(formatDateOnly("2026-12-31"), "Dec 31, 2026");
  assert.equal(formatDateOnly("2026-12-31T00:00:00+00:00"), "Dec 31, 2026");
});

test("uses the New York quarter at a UTC month boundary", () => {
  assert.equal(currentBusinessQuarter(new Date("2026-05-01T00:30:00Z")), 1);
});

test("keeps business dates explicit across the 2026 fall-back boundary", () => {
  assert.equal(businessDate(new Date("2026-11-01T03:59:59Z")), "2026-10-31");
  assert.equal(businessDate(new Date("2026-11-01T04:00:00Z")), "2026-11-01");
});
