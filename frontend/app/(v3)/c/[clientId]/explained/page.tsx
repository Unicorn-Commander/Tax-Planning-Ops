import { SurfaceStub } from "../../../shell";

export default function ExplainedPage() {
  return (
    <SurfaceStub
      no="16"
      title="Your return, in plain English"
      intent="The first-value payoff — the 'now I get it' screen after import. A calm keep-vs-tax summary, six plain chapters (income · deductions/QBI · the bracket walk as 'layers' · true next-dollar rate · the lines to watch · where you could do better), every expert term a 'what's this?' → plain gloss. A 'Plain English ⟷ The detail' register toggle links this calm view to the dense case/lab. Doubles as the firm's client-facing education artifact."
      mockup="16-explainer.html"
      live="engines + narration (LLM narrates in plain language; cannot change a number)."
      additive="the explainer renderer + register toggle. The global gloss map already lives in kit/tokens (GLOSS)."
    />
  );
}
