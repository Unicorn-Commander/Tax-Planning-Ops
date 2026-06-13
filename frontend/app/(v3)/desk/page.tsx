import { SurfaceStub } from "../shell";

export default function DeskPage() {
  return (
    <SurfaceStub
      no="01"
      title="The Desk"
      intent="The firm command deck: the sign-off queue, the season strip, the book pulse ranked by recomputed savings, the duty band, the omnibar, and the audit ticker."
      mockup="01-desk.html"
      live="quarterly per client + GET /agents/scan-book (do NOT re-sort by total_tax). Sign-off queue from unconfirmed extractions + pending finalize + AO sync."
      additive="persisted memo drafts · agent registry/status (duty band) · journal read API (ticker)."
    />
  );
}
