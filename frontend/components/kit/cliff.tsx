// kit/cliff.tsx — the cliff radar row (§7-03) and the three-rate cluster.
//
// CliffRow shows a threshold "with teeth" as a SHEER STEP EDGE (never a gauge):
// distance to the line and the cost of crossing it, the binding side
// underlined; IRMAA carries its income-year → premium-year mapping.

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Money } from "./primitives";
import { Term } from "./term";

/** The sheer-edge glyph: flat, then a vertical drop — the cliff, not a ramp. */
function StepEdge({ proximity }: { proximity: number }) {
  // proximity 0..1 = how close to the edge (1 = at it). Edge sits proximity-near the right.
  const x = 18 + Math.max(0, Math.min(1, proximity)) * 86;
  return (
    <svg width="120" height="26" viewBox="0 0 120 26" aria-hidden className="flex-none">
      <path
        d={`M2 7 H${x} V22 H118`}
        fill="none"
        stroke="var(--cliff)"
        strokeWidth="1.5"
        strokeLinejoin="miter"
      />
      <circle cx={x} cy="7" r="2.5" fill="var(--cliff)" />
    </svg>
  );
}

export function CliffRow({
  label,
  glossKey,
  thresholdCents,
  distanceCents,
  costOfCrossingCents,
  mapping,
  binding = "below",
  className,
}: {
  label: ReactNode;
  /** optional gloss key so the label carries a "what's this?" */
  glossKey?: Parameters<typeof Term>[0]["k"];
  thresholdCents: number;
  /** how far below the line (positive) the client sits */
  distanceCents: number;
  /** the annual tax/premium hit if crossed */
  costOfCrossingCents: number;
  /** IRMAA-style income-year → premium-year note */
  mapping?: string;
  /** which side is the binding constraint (underlined) */
  binding?: "below" | "cost";
  className?: string;
}) {
  const proximity = thresholdCents > 0 ? 1 - Math.min(1, distanceCents / thresholdCents) : 0.5;
  return (
    <div className={cn("flex items-center gap-4 border-t border-[var(--g-hairline-soft)] py-3 first:border-t-0", className)}>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold">
          {glossKey ? <Term k={glossKey}>{label}</Term> : label}
        </div>
        {mapping ? <div className="mt-0.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">{mapping}</div> : null}
      </div>
      <StepEdge proximity={proximity} />
      <div className="flex flex-none items-baseline gap-5 text-right">
        <div>
          <div className="microlabel">below</div>
          <div className={cn("text-[13px]", binding === "below" && "underline decoration-[var(--cliff)] underline-offset-4")}>
            <Money cents={distanceCents} />
          </div>
        </div>
        <div>
          <div className="microlabel">crossing costs</div>
          <div className={cn("text-[13px] tone-cliff", binding === "cost" && "underline decoration-[var(--cliff)] underline-offset-4")}>
            <Money cents={costOfCrossingCents} />/yr
          </div>
        </div>
      </div>
    </div>
  );
}

/** The three-rate cluster: nominal · true next-dollar · average (§7-03). */
export function RateCluster({
  nominal,
  trueMarginal,
  effective,
  className,
}: {
  nominal: number;
  /** [additive: EMR] — when present and >2pts from nominal, it's highlighted */
  trueMarginal?: number;
  effective: number;
  className?: string;
}) {
  const diverges = trueMarginal !== undefined && Math.abs(trueMarginal - nominal) > 0.02;
  const fmt = (r: number) => `${(r * 100).toFixed(1)}%`;
  return (
    <div className={cn("flex flex-wrap gap-x-8 gap-y-3", className)}>
      <Rate label={<Term k="nominal-bracket">nominal bracket</Term>} value={fmt(nominal)} />
      <Rate
        label={<Term k="marginal-rate">true next-dollar</Term>}
        value={trueMarginal !== undefined ? fmt(trueMarginal) : "—"}
        tone={diverges ? "cliff" : undefined}
        note={diverges ? `+${((trueMarginal! - nominal) * 100).toFixed(0)}pts vs bracket` : trueMarginal === undefined ? "EMR pending" : undefined}
      />
      <Rate label={<Term k="effective-rate">average</Term>} value={fmt(effective)} />
    </div>
  );
}

function Rate({ label, value, tone, note }: { label: ReactNode; value: string; tone?: "cliff"; note?: string }) {
  return (
    <div>
      <div className="microlabel">{label}</div>
      <div className={cn("fig mt-1 text-[24px] font-semibold leading-none tracking-tight", tone && `tone-${tone}`)}>{value}</div>
      {note ? <div className={cn("mt-1 text-[11px]", tone ? `tone-${tone}` : "text-[var(--g-ink-3)]")}>{note}</div> : null}
    </div>
  );
}
