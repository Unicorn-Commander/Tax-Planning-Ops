// kit/position.tsx — THE POSITION INSTRUMENT (§0.1, §7-03). The product's
// signature: income filling the marginal-rate strata, with the NOW marker,
// cliff pins, a headroom band, and an optional LTCG lane stacked above.
//
// HARD RULE (§0.1): segment widths are proportional to REAL bracket dollar
// spans (from the bracket sets), never equal-width rows. The caller passes
// segments straight from GET /admin/tax-bracket-sets; this never hardcodes
// bracket dollars.

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { strataColor, STRATA_CG } from "./tokens";
import type { Vars } from "./primitives";

export interface Segment {
  rate: number;        // marginal rate, e.g. 0.22
  fromCents: number;
  toCents: number;     // top bracket: pass a finite display ceiling
}
export interface Pin {
  atCents: number;
  label: string;
  soft?: boolean;      // amber (phase-out) vs crimson (cliff)
}
export interface Headroom {
  fromCents: number;
  toCents: number;
  label: string;
}

/** Compact axis label: $0 / $48k / $1.2M. */
function compact(cents: number): string {
  const d = cents / 100;
  if (d >= 1_000_000) return `$${(d / 1_000_000).toFixed(d % 1_000_000 ? 1 : 0)}M`;
  if (d >= 1_000) return `$${Math.round(d / 1_000)}k`;
  return `$${Math.round(d)}`;
}

function pct(v: number, min: number, span: number) {
  return `${Math.max(0, Math.min(100, ((v - min) / span) * 100))}%`;
}

export function PositionInstrument({
  segments,
  incomeCents,
  nowLabel,
  pins = [],
  headroom,
  ltcg,
  variant = "hero",
  className,
}: {
  segments: Segment[];
  incomeCents: number;
  nowLabel?: ReactNode;
  pins?: Pin[];
  headroom?: Headroom;
  ltcg?: Segment[];
  variant?: "hero" | "bar" | "micro";
  className?: string;
}) {
  if (segments.length === 0) return null;
  const axisMin = segments[0].fromCents;
  const axisMax = segments[segments.length - 1].toCents;
  const span = Math.max(1, axisMax - axisMin);

  /* ---- micro: the roster-row variant (no labels) ---- */
  if (variant === "micro") {
    return (
      <span className={cn("inst-micro", className)}>
        {segments.map((s, i) => {
          const w = ((s.toCents - s.fromCents) / span) * 100;
          const filled = incomeCents >= s.toCents;
          const partial = incomeCents > s.fromCents && incomeCents < s.toCents;
          const fillpct = partial ? ((incomeCents - s.fromCents) / (s.toCents - s.fromCents)) * 100 : 0;
          return (
            <i
              key={i}
              style={{
                width: `${w}%`,
                background: strataColor(s.rate),
                opacity: filled ? 0.9 : partial ? 0.9 : 0.22,
                ...(partial
                  ? ({
                      WebkitMask: `linear-gradient(90deg,#000 ${fillpct}%,rgba(0,0,0,0.25) ${fillpct}%)`,
                      mask: `linear-gradient(90deg,#000 ${fillpct}%,rgba(0,0,0,0.25) ${fillpct}%)`,
                    } as Vars)
                  : {}),
              }}
            />
          );
        })}
        {pins.map((p, i) => (
          <span key={i} className="pin" style={{ left: pct(p.atCents, axisMin, span) }} title={p.label} />
        ))}
      </span>
    );
  }

  const showLabels = variant === "hero";

  return (
    <div className={cn("instrument", className)}>
      {/* the optional LTCG lane, stacked above the ordinary track */}
      {ltcg && ltcg.length > 0 ? (
        <div className="inst-track mb-1" style={{ height: 12 }}>
          {ltcg.map((s, i) => {
            const w = ((s.toCents - s.fromCents) / span) * 100;
            const filled = incomeCents >= s.fromCents;
            return (
              <div key={i} className={cn("inst-seg", filled && "filled")} style={{ width: `${w}%` } as Vars}>
                <i style={{ background: STRATA_CG[s.rate] ?? "var(--cg15)" } as Vars} />
              </div>
            );
          })}
        </div>
      ) : null}

      <div className="inst-track" style={{ height: variant === "bar" ? 36 : 56 }}>
        {/* headroom band (behind segments) */}
        {headroom ? (
          <div
            className="inst-headroom"
            style={{ left: pct(headroom.fromCents, axisMin, span), width: pct(headroom.toCents - headroom.fromCents + axisMin, axisMin, span) }}
          >
            {showLabels ? <span className="tag">{headroom.label}</span> : null}
          </div>
        ) : null}

        {segments.map((s, i) => {
          const w = ((s.toCents - s.fromCents) / span) * 100;
          const filled = incomeCents >= s.toCents;
          const partial = incomeCents > s.fromCents && incomeCents < s.toCents;
          const fillpct = partial ? ((incomeCents - s.fromCents) / (s.toCents - s.fromCents)) * 100 : 50;
          return (
            <div
              key={i}
              className={cn("inst-seg", filled && "filled", partial && "partial")}
              style={{ width: `${w}%`, "--seg": strataColor(s.rate), "--fillpct": `${fillpct}%` } as Vars}
            >
              <i />
              {showLabels ? <span className="rt">{Math.round(s.rate * 100)}%</span> : null}
              {showLabels ? <span className="bd">{compact(s.fromCents)}</span> : null}
            </div>
          );
        })}

        {/* cliff / phase-out pins */}
        {pins.map((p, i) => (
          <div key={i} className={cn("inst-pin", p.soft && "soft")} style={{ left: pct(p.atCents, axisMin, span) }}>
            <span className="tag">{p.label}</span>
          </div>
        ))}

        {/* the NOW marker (income) */}
        <div className="inst-now" style={{ left: pct(incomeCents, axisMin, span) }}>
          {nowLabel ? <span className="tag">{nowLabel}</span> : null}
        </div>
      </div>
    </div>
  );
}
