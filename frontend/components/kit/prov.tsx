"use client";

// kit/prov.tsx — "no naked numbers" (§0.3). Every dollar figure is interrogable:
// ProvFigure renders the money with a dotted underline and reveals a ProvCard
// (engine + version · key inputs · constants w/ citation · audit ref) on
// hover / focus / tap. SourceMark binds a figure to where it came from.
//
// Honesty: a figure with no `prov` renders as a plain tabular number (no dotted
// underline) — surfaces supply provenance as the [additive] endpoints land,
// never faking a lineage. The LLM can never be a source.

import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { centsToUSD } from "@/lib/format";
import type { SourceClass, Tone } from "./tokens";

export interface Provenance {
  /** what this figure is, e.g. "2025 total tax" */
  label?: string;
  /** engine + version, e.g. "federal_engine · v2.3" */
  engine?: string;
  /** key inputs the engine consumed */
  inputs?: { k: string; v: string }[];
  /** constants used, with Rev. Proc. / statute citation in the value */
  constants?: { k: string; v: string }[];
  /** audit reference / run id */
  auditRef?: string;
  /** binding source class (drives the SourceMark color) */
  source?: SourceClass;
}

const SOURCE_GLYPH: Record<SourceClass, string> = {
  engine: "∑",
  document: "¶",
  books: "❖",
};
const SOURCE_LABEL: Record<SourceClass, string> = {
  engine: "Engine-computed",
  document: "From the document",
  books: "From the books (AO)",
};

/** The small colored marker that binds a figure to its source class (§0.3). */
export function SourceMark({ source, title }: { source: SourceClass; title?: string }) {
  return (
    <sup
      className="ml-0.5 font-mono text-[10px] align-super"
      style={{ color: source === "engine" ? "var(--agent)" : source === "document" ? "#3f63a0" : "var(--seal)" }}
      title={title ?? SOURCE_LABEL[source]}
    >
      {SOURCE_GLYPH[source]}
    </sup>
  );
}

/** The lineage card revealed by a ProvFigure. */
export function ProvCard({ value, prov }: { value: ReactNode; prov: Provenance }) {
  return (
    <div className="prov-card" role="dialog" aria-label="figure provenance">
      <div className="ph">
        <b className="fig">{value}</b>
        <span className="microlabel">{prov.label ?? "figure"}</span>
        {prov.source ? <span className="ml-auto"><SourceMark source={prov.source} /></span> : null}
      </div>
      {prov.engine ? (
        <div className="prov-row"><span className="k">engine</span><span className="v">{prov.engine}</span></div>
      ) : null}
      {prov.inputs?.map((r) => (
        <div className="prov-row" key={`i-${r.k}`}><span className="k">{r.k}</span><span className="v">{r.v}</span></div>
      ))}
      {prov.constants?.map((r) => (
        <div className="prov-row" key={`c-${r.k}`}><span className="k">{r.k}</span><span className="v">{r.v}</span></div>
      ))}
      {prov.auditRef ? (
        <div className="prov-row"><span className="k">audit</span><span className="v">{prov.auditRef}</span></div>
      ) : null}
    </div>
  );
}

/**
 * An interrogable money figure. Pass `cents` (integer cents) or `children`
 * (pre-formatted). With `prov`, it gets the dotted underline + the hover card.
 */
export function ProvFigure({
  cents,
  children,
  prov,
  tone,
  className,
  signed,
}: {
  cents?: number;
  children?: ReactNode;
  prov?: Provenance;
  tone?: Tone;
  className?: string;
  signed?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();

  const text =
    children ??
    (cents !== undefined
      ? `${signed ? (cents > 0 ? "+" : cents < 0 ? "−" : "") : ""}${centsToUSD(Math.abs(cents))}`
      : "—");

  const valueSpan = (
    <span className={cn("money fig", tone && `tone-${tone}`, className)}>{text}</span>
  );

  // No provenance → a plain, honest, still-tabular figure.
  if (!prov) return valueSpan;

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        className={cn("prov money fig bg-transparent p-0 text-left", tone && `tone-${tone}`, className)}
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {text}
        {prov.source ? <SourceMark source={prov.source} /> : null}
      </button>
      {open ? (
        <span id={id} className="absolute bottom-[calc(100%+8px)] left-0 z-40 cursor-default" onClick={(e) => e.stopPropagation()}>
          <ProvCard value={text} prov={prov} />
        </span>
      ) : null}
    </span>
  );
}
