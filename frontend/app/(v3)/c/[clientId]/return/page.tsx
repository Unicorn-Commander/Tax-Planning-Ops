import { SurfaceStub } from "../../../shell";

export default function ReturnPage() {
  return (
    <SurfaceStub
      no="04"
      title="The Return"
      intent="Import theater: the scan pane with live bounding boxes, fields sorted lowest-confidence-first, the flagged field with a source crop + Confirm/Correct. THE VERIFICATION GATE: 'engine recomputed total tax $X — matches the return exactly ✓' before baseline confirm; a mismatch blocks with a per-line diff. Below: the waterfall + the line ledger with source dots."
      mockup="04-return.html"
      live="extracted-returns + PATCH field + confirm. Engines recompute vs extracted totals — wire the comparison into the confirm flow (the gate)."
      additive="bbox in the OCR payload (degrade to field-list-only). Gate logic = frontier."
    />
  );
}
