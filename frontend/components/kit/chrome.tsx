// kit/chrome.tsx — shared chrome bits: the Wordmark (strata underline), the
// engagement StagePipeline (§7-03), and the audit-journal Ticker (§7-01).

import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { Stage } from "./primitives";

/** The brand wordmark — the strata is its underline. */
export function Wordmark({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn("wordmark", className)}>
      <span className="mk" />
      <b>Tax-Planning-Ops</b>
    </Link>
  );
}

export type StageState = "todo" | "on" | "done" | "sealed";
export interface PipelineStage {
  label: string;
  state: StageState;
}
/** The engagement pipeline: intake → baseline → analysis → memo → signed → … */
export function StagePipeline({ stages, className }: { stages: PipelineStage[]; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-2", className)}>
      {stages.map((s, i) => (
        <Stage key={i} state={s.state}>{s.label}</Stage>
      ))}
    </div>
  );
}

export interface TickItem {
  tone?: "save" | "cost" | "cliff" | "agent" | "seal";
  label: ReactNode;
  value?: ReactNode;
}
/**
 * The audit-journal ticker (§7-01). Items are doubled so the -50% crawl loops
 * seamlessly; pauses on hover; killed by prefers-reduced-motion (globals.css).
 * [additive: journal read API] — v1 can pass recent activity, or omit it.
 */
export function Ticker({ items, className }: { items: TickItem[]; className?: string }) {
  if (items.length === 0) return null;
  const row = (keyPrefix: string) =>
    items.map((it, i) => (
      <span className="tick-item" key={`${keyPrefix}-${i}`}>
        <span className="t-dot" style={{ background: `var(--${it.tone ?? "info"})` }} />
        {it.value !== undefined ? (
          <>
            <span>{it.label}</span> <b>{it.value}</b>
          </>
        ) : (
          <span>{it.label}</span>
        )}
      </span>
    ));
  return (
    <div className={cn("ticker", className)} aria-hidden>
      <div className="ticker-track">
        {row("a")}
        {row("b")}
      </div>
    </div>
  );
}
