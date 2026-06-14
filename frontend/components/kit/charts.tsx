// kit/charts.tsx — the procedural-SVG chart primitives (DESIGN-SPEC §10, §11:
// "procedural SVG only, no chart lib"). Built by frontier so the chart-heavy
// surfaces (Return/Plan/Entities/Lab) share one visual language instead of
// reinventing SVG per agent. Every series is engine data passed as props; these
// draw, they never compute a tax figure.
//
// Shared conventions: a viewBox frame, tokens for color (--save/--cost/--cliff/
// --g-ink + the strata), tabular labels, one-time draw-in left to the caller.

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Compact axis money: $0 / $48k / $1.2M. */
function k(cents: number): string {
  const d = cents / 100;
  const sign = d < 0 ? "−" : "";
  const a = Math.abs(d);
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(a % 1_000_000 ? 1 : 0)}M`;
  if (a >= 1_000) return `${sign}$${Math.round(a / 1_000)}k`;
  return `${sign}$${Math.round(a)}`;
}

/* ======================================================== WaterfallSVG ===== */
// income → AGI → deductions → taxable → tax → payments → refund. Each step is
// an engine line; bars float from the running total. (Return 04.)
export interface WaterfallStep {
  label: string;
  cents: number;
  /** base/result = full bar from 0 (a checkpoint); add/subtract = floating delta */
  kind: "base" | "add" | "subtract" | "result";
}
export function WaterfallSVG({ steps, height = 230, className }: { steps: WaterfallStep[]; height?: number; className?: string }) {
  if (steps.length === 0) return null;
  const W = Math.max(360, steps.length * 96);
  const padX = 16, padTop = 22, padBottom = 46;
  const plotH = height - padTop - padBottom;

  // running totals → each bar's [topCents, bottomCents]
  let run = 0;
  const bars = steps.map((s) => {
    let top: number, bottom: number;
    if (s.kind === "base" || s.kind === "result") { top = s.cents; bottom = 0; run = s.cents; }
    else if (s.kind === "add") { bottom = run; run += s.cents; top = run; }
    else { top = run; run -= s.cents; bottom = run; }
    return { ...s, top, bottom };
  });
  const maxV = Math.max(...bars.map((b) => Math.max(b.top, b.bottom)), 1);
  const y = (v: number) => padTop + plotH * (1 - v / maxV);
  const colW = (W - padX * 2) / steps.length;
  const barW = Math.min(54, colW * 0.6);

  const tone = (kind: WaterfallStep["kind"]) =>
    kind === "subtract" ? "var(--save)" : kind === "add" ? "var(--cost)" : "var(--g-ink)";

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("w-full", className)} role="img" aria-label="tax waterfall">
      {bars.map((b, i) => {
        const cx = padX + colW * i + colW / 2;
        const yTop = y(Math.max(b.top, b.bottom));
        const h = Math.abs(y(b.bottom) - y(b.top));
        const fill = tone(b.kind);
        const solid = b.kind === "base" || b.kind === "result";
        return (
          <g key={i}>
            {i > 0 ? (
              <line x1={padX + colW * (i - 1) + colW / 2 + barW / 2} y1={y(bars[i - 1].top)} x2={cx - barW / 2} y2={y(bars[i - 1].top)} stroke="var(--g-hairline)" strokeDasharray="2 2" />
            ) : null}
            <rect x={cx - barW / 2} y={yTop} width={barW} height={Math.max(2, h)} rx={2} fill={fill} fillOpacity={solid ? 0.9 : 0.7} />
            <text x={cx} y={yTop - 5} textAnchor="middle" className="fill-[var(--g-ink)] font-mono" fontSize="9.5">{k(b.kind === "subtract" ? -b.cents : b.cents)}</text>
            <text x={cx} y={height - padBottom + 16} textAnchor="middle" className="fill-[var(--g-ink-3)]" fontSize="9.5">{b.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ====================================================== SafeHarborChart ===== */
// cumulative REQUIRED step line (22.5/45/67.5/90%) vs cumulative PAID; dips
// below shade red with the 2210 penalty. (Plan 07.)
export function SafeHarborChart({
  requiredCumCents,
  paidCumCents,
  penaltyCents,
  height = 200,
  className,
}: {
  requiredCumCents: number[];
  paidCumCents: number[];
  penaltyCents?: number;
  height?: number;
  className?: string;
}) {
  const n = Math.max(requiredCumCents.length, paidCumCents.length, 2);
  const W = 520, padX = 40, padTop = 18, padBottom = 32;
  const plotH = height - padTop - padBottom;
  const maxV = Math.max(...requiredCumCents, ...paidCumCents, 1);
  const x = (i: number) => padX + ((W - padX * 2) * i) / (n - 1);
  const y = (v: number) => padTop + plotH * (1 - v / maxV);
  const reqPts = requiredCumCents.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const paidPts = paidCumCents.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  // shaded shortfall area (paid below required)
  const shortfall = requiredCumCents.map((rv, i) => {
    const pv = paidCumCents[i] ?? 0;
    return pv < rv ? { i, rv, pv } : null;
  }).filter(Boolean) as { i: number; rv: number; pv: number }[];

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("w-full", className)} role="img" aria-label="safe harbor: required vs paid">
      {[0.25, 0.5, 0.75, 1].map((g) => (
        <line key={g} x1={padX} y1={y(maxV * g)} x2={W - padX} y2={y(maxV * g)} stroke="var(--g-hairline-soft)" />
      ))}
      {shortfall.map((s) => (
        <rect key={s.i} x={x(s.i) - 6} y={y(s.rv)} width={12} height={Math.max(0, y(s.pv) - y(s.rv))} fill="var(--cliff)" fillOpacity={0.16} />
      ))}
      <polyline points={reqPts} fill="none" stroke="var(--g-ink-3)" strokeWidth={1.5} strokeDasharray="4 3" />
      <polyline points={paidPts} fill="none" stroke="var(--save)" strokeWidth={2} />
      {paidCumCents.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={3} fill="var(--save)" />)}
      {Array.from({ length: n }).map((_, i) => (
        <text key={i} x={x(i)} y={height - 12} textAnchor="middle" className="fill-[var(--g-ink-3)] font-mono" fontSize="9.5">Q{i + 1}</text>
      ))}
      <text x={padX} y={y(maxV) - 5} className="fill-[var(--g-ink-3)] font-mono" fontSize="9">{k(maxV)}</text>
      {penaltyCents ? (
        <text x={W - padX} y={padTop + 4} textAnchor="end" className="fill-[var(--cliff)] font-mono" fontSize="10">2210 penalty {k(penaltyCents)}</text>
      ) : null}
    </svg>
  );
}

/* ========================================================= SalaryCurve ===== */
// net benefit vs salary, optimum pin, reasonable-comp floor zone. (Entities 08.)
export function SalaryCurve({
  points,
  optimumSalaryCents,
  floorFromCents,
  floorToCents,
  height = 220,
  className,
}: {
  points: { salaryCents: number; netBenefitCents: number }[];
  optimumSalaryCents?: number;
  floorFromCents?: number;
  floorToCents?: number;
  height?: number;
  className?: string;
}) {
  if (points.length < 2) return null;
  const W = 520, padX = 44, padTop = 22, padBottom = 34;
  const plotH = height - padTop - padBottom;
  const xs = points.map((p) => p.salaryCents);
  const ys = points.map((p) => p.netBenefitCents);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys, 0), yMax = Math.max(...ys, 1);
  const X = (c: number) => padX + ((W - padX * 2) * (c - xMin)) / Math.max(1, xMax - xMin);
  const Y = (c: number) => padTop + plotH * (1 - (c - yMin) / Math.max(1, yMax - yMin));
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${X(p.salaryCents)},${Y(p.netBenefitCents)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("w-full", className)} role="img" aria-label="S-corp salary optimization curve">
      {floorFromCents !== undefined && floorToCents !== undefined ? (
        <g>
          <rect x={X(floorFromCents)} y={padTop} width={Math.max(0, X(floorToCents) - X(floorFromCents))} height={plotH} fill="var(--cost)" fillOpacity={0.08} />
          <text x={(X(floorFromCents) + X(floorToCents)) / 2} y={padTop + 12} textAnchor="middle" className="fill-[var(--cost)] font-mono" fontSize="9">reasonable-comp floor</text>
        </g>
      ) : null}
      <line x1={padX} y1={Y(0)} x2={W - padX} y2={Y(0)} stroke="var(--g-hairline)" />
      <path d={path} fill="none" stroke="var(--agent)" strokeWidth={2} />
      {optimumSalaryCents !== undefined ? (
        (() => {
          const opt = points.reduce((a, b) => (Math.abs(b.salaryCents - optimumSalaryCents) < Math.abs(a.salaryCents - optimumSalaryCents) ? b : a));
          return (
            <g>
              <line x1={X(opt.salaryCents)} y1={padTop} x2={X(opt.salaryCents)} y2={height - padBottom} stroke="var(--save)" strokeDasharray="3 2" />
              <circle cx={X(opt.salaryCents)} cy={Y(opt.netBenefitCents)} r={4} fill="var(--save)" />
              <text x={X(opt.salaryCents)} y={Y(opt.netBenefitCents) - 8} textAnchor="middle" className="fill-[var(--save)] font-mono" fontSize="9.5">optimum {k(opt.salaryCents)}</text>
            </g>
          );
        })()
      ) : null}
      <text x={padX} y={height - 12} textAnchor="middle" className="fill-[var(--g-ink-3)] font-mono" fontSize="9">{k(xMin)}</text>
      <text x={W - padX} y={height - 12} textAnchor="middle" className="fill-[var(--g-ink-3)] font-mono" fontSize="9">{k(xMax)}</text>
    </svg>
  );
}

/* =========================================================== EntityMap ===== */
// entity nodes → labeled flows → the 1040 hub → household rollup. (Entities 08.)
// A schematic three-column layout (entities · hub · rollup), engine amounts.
export interface EntityNode {
  id: string;
  label: string;
  sublabel?: string;
  kind: "entity" | "hub" | "rollup";
  amountCents?: number;
  hue?: string;
}
export interface EntityEdge { from: string; to: string; label?: string }
export function EntityMap({ nodes, edges, height = 280, className }: { nodes: EntityNode[]; edges: EntityEdge[]; height?: number; className?: string }) {
  const W = 640;
  const entities = nodes.filter((n) => n.kind === "entity");
  const hub = nodes.find((n) => n.kind === "hub");
  const rollup = nodes.find((n) => n.kind === "rollup");
  const colX = { entity: 110, hub: 320, rollup: 540 };
  const boxW = 150, boxH = 50;
  const pos: Record<string, { x: number; y: number }> = {};
  entities.forEach((n, i) => { pos[n.id] = { x: colX.entity, y: 40 + i * (height - 80) / Math.max(1, entities.length - 1 || 1) }; });
  if (entities.length === 1) pos[entities[0].id] = { x: colX.entity, y: height / 2 };
  if (hub) pos[hub.id] = { x: colX.hub, y: height / 2 };
  if (rollup) pos[rollup.id] = { x: colX.rollup, y: height / 2 };

  const Node = ({ n }: { n: EntityNode }) => {
    const p = pos[n.id]; if (!p) return null;
    const hue = n.hue ?? (n.kind === "hub" ? "var(--g-ink)" : n.kind === "rollup" ? "var(--seal)" : "var(--agent)");
    return (
      <g>
        <rect x={p.x - boxW / 2} y={p.y - boxH / 2} width={boxW} height={boxH} rx={8} fill="var(--g-surface)" stroke={hue} strokeOpacity={0.5} />
        <rect x={p.x - boxW / 2} y={p.y - boxH / 2} width={3} height={boxH} rx={1.5} fill={hue} />
        <text x={p.x - boxW / 2 + 12} y={p.y - 4} className="fill-[var(--g-ink)]" fontSize="11.5" fontWeight="600">{n.label.length > 18 ? n.label.slice(0, 17) + "…" : n.label}</text>
        {n.sublabel ? <text x={p.x - boxW / 2 + 12} y={p.y + 11} className="fill-[var(--g-ink-3)] font-mono" fontSize="8.5">{n.sublabel}</text> : null}
        {n.amountCents !== undefined ? <text x={p.x + boxW / 2 - 10} y={p.y - 4} textAnchor="end" className="fill-[var(--g-ink)] font-mono" fontSize="10">{k(n.amountCents)}</text> : null}
      </g>
    );
  };

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("w-full", className)} role="img" aria-label="entity structure map">
      {edges.map((e, i) => {
        const a = pos[e.from], b = pos[e.to]; if (!a || !b) return null;
        const x1 = a.x + boxW / 2, x2 = b.x - boxW / 2;
        const mx = (x1 + x2) / 2;
        return (
          <g key={i}>
            <path d={`M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}`} fill="none" stroke="var(--g-hairline)" strokeWidth={1.5} markerEnd="url(#emArrow)" />
            {e.label ? <text x={mx} y={(a.y + b.y) / 2 - 4} textAnchor="middle" className="fill-[var(--g-ink-3)] font-mono" fontSize="8.5">{e.label}</text> : null}
          </g>
        );
      })}
      <defs>
        <marker id="emArrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="var(--g-ink-3)" /></marker>
      </defs>
      {nodes.map((n) => <Node key={n.id} n={n} />)}
    </svg>
  );
}

/* ========================================================== EMRTerrain ===== */
// the true effective-marginal-rate curve over +$X income, statutory steps dashed
// behind, spikes labeled. (Lab 05 — Phase 2.)
export function EMRTerrain({
  points,
  statutory,
  spikes,
  height = 240,
  className,
}: {
  points: { incomeCents: number; ratePct: number }[];
  statutory?: { incomeCents: number; ratePct: number }[];
  spikes?: { incomeCents: number; label: string }[];
  height?: number;
  className?: string;
}) {
  if (points.length < 2) return null;
  const W = 560, padX = 40, padTop = 24, padBottom = 30;
  const plotH = height - padTop - padBottom;
  const xs = points.map((p) => p.incomeCents);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const rMax = Math.max(...points.map((p) => p.ratePct), ...(statutory ?? []).map((s) => s.ratePct), 0.4);
  const X = (c: number) => padX + ((W - padX * 2) * (c - xMin)) / Math.max(1, xMax - xMin);
  const Y = (r: number) => padTop + plotH * (1 - r / rMax);
  const line = (pts: { incomeCents: number; ratePct: number }[]) => pts.map((p, i) => `${i === 0 ? "M" : "L"}${X(p.incomeCents)},${Y(p.ratePct)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("w-full", className)} role="img" aria-label="effective marginal rate terrain">
      {[0.1, 0.2, 0.3, 0.4].filter((g) => g <= rMax).map((g) => (
        <g key={g}>
          <line x1={padX} y1={Y(g)} x2={W - padX} y2={Y(g)} stroke="var(--g-hairline-soft)" />
          <text x={padX - 6} y={Y(g) + 3} textAnchor="end" className="fill-[var(--g-ink-3)] font-mono" fontSize="8.5">{Math.round(g * 100)}%</text>
        </g>
      ))}
      {statutory ? <path d={line(statutory)} fill="none" stroke="var(--g-ink-3)" strokeWidth={1.25} strokeDasharray="4 3" /> : null}
      <path d={line(points)} fill="none" stroke="var(--cliff)" strokeWidth={2} />
      {spikes?.map((s, i) => (
        <g key={i}>
          <line x1={X(s.incomeCents)} y1={padTop} x2={X(s.incomeCents)} y2={height - padBottom} stroke="var(--cliff)" strokeDasharray="2 2" strokeOpacity={0.6} />
          <text x={X(s.incomeCents)} y={padTop - 6} textAnchor="middle" className="fill-[var(--cliff)] font-mono" fontSize="8.5">{s.label}</text>
        </g>
      ))}
      <text x={padX} y={height - 10} className="fill-[var(--g-ink-3)] font-mono" fontSize="9">{k(xMin)}</text>
      <text x={W - padX} y={height - 10} textAnchor="end" className="fill-[var(--g-ink-3)] font-mono" fontSize="9">{k(xMax)}</text>
    </svg>
  );
}

/* ======================================================= CrossoverChart ===== */
// cumulative two-line, gap labeled at the horizon. (Lab 05 — the Roth ladder.)
export function CrossoverChart({
  series,
  crossoverLabel,
  height = 220,
  className,
}: {
  series: { label: string; tone?: "save" | "cost" | "ink"; points: { year: number; cents: number }[] }[];
  crossoverLabel?: string;
  height?: number;
  className?: string;
}) {
  if (series.length === 0) return null;
  const W = 540, padX = 44, padTop = 20, padBottom = 30;
  const plotH = height - padTop - padBottom;
  const allPts = series.flatMap((s) => s.points);
  const years = allPts.map((p) => p.year);
  const yMin = Math.min(...years), yMax = Math.max(...years);
  const vMax = Math.max(...allPts.map((p) => p.cents), 1);
  const X = (yr: number) => padX + ((W - padX * 2) * (yr - yMin)) / Math.max(1, yMax - yMin);
  const Y = (c: number) => padTop + plotH * (1 - c / vMax);
  const toneVar = (t?: string) => (t === "save" ? "var(--save)" : t === "cost" ? "var(--cost)" : "var(--g-ink)");

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("w-full", className)} role="img" aria-label="cumulative crossover">
      <line x1={padX} y1={Y(0)} x2={W - padX} y2={Y(0)} stroke="var(--g-hairline)" />
      {series.map((s, i) => (
        <g key={i}>
          <polyline points={s.points.map((p) => `${X(p.year)},${Y(p.cents)}`).join(" ")} fill="none" stroke={toneVar(s.tone)} strokeWidth={2} />
          <text x={X(s.points[s.points.length - 1].year)} y={Y(s.points[s.points.length - 1].cents) - 6} textAnchor="end" className="font-mono" fontSize="9" fill={toneVar(s.tone)}>{s.label}</text>
        </g>
      ))}
      {[yMin, Math.round((yMin + yMax) / 2), yMax].map((yr) => (
        <text key={yr} x={X(yr)} y={height - 10} textAnchor="middle" className="fill-[var(--g-ink-3)] font-mono" fontSize="9">{yr}</text>
      ))}
      {crossoverLabel ? <text x={W - padX} y={padTop + 4} textAnchor="end" className="fill-[var(--save)] font-mono" fontSize="10">{crossoverLabel}</text> : null}
    </svg>
  );
}

/** A tiny legend row for any chart. */
export function ChartLegend({ items, className }: { items: { label: ReactNode; tone: string; dashed?: boolean }[]; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 font-mono text-[10px] text-[var(--g-ink-3)]", className)}>
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          <svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4" stroke={it.tone} strokeWidth="2" strokeDasharray={it.dashed ? "3 2" : undefined} /></svg>
          {it.label}
        </span>
      ))}
    </div>
  );
}
