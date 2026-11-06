import assert from "node:assert/strict";
import test from "node:test";
import { staggerLabels } from "./chart-labels.ts";

test("puts NIIT and IRMAA tier 4 on different rows when centers are ~24px apart", () => {
  const placed = staggerLabels([
    { x: 200, text: "NIIT 3.8% threshold" },
    { x: 224, text: "IRMAA tier 4" },
  ]);
  assert.equal(placed[0].row, 0);
  assert.equal(placed[1].row, 1);
  assert.notEqual(placed[0].row, placed[1].row);
});

test("keeps labels that clear each other on row 0", () => {
  const placed = staggerLabels([
    { x: 40, text: "NIIT 3.8%" },
    { x: 400, text: "IRMAA tier 5" },
  ]);
  assert.equal(placed[0].row, 0);
  assert.equal(placed[1].row, 0);
});

test("preserves input order when the right-hand label is placed first", () => {
  const placed = staggerLabels([
    { x: 300, text: "IRMAA tier 5" },
    { x: 80, text: "NIIT 3.8%" },
  ]);
  assert.equal(placed[0].text, "IRMAA tier 5");
  assert.equal(placed[1].text, "NIIT 3.8%");
  assert.equal(placed[0].row, 0);
  assert.equal(placed[1].row, 0);
});
