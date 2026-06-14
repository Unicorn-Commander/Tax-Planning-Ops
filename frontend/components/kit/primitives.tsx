// kit/primitives.tsx — the atoms. Pure, presentational, no hooks (usable from
// server or client). Typed wrappers over the component classes in globals.css.

import type { ComponentProps, CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { centsToUSD } from "@/lib/format";
import { hueForClient, type AgentKey, AGENT_HUES, type Tone } from "./tokens";

/** Allow CSS custom properties (--chue / --ahue / --seg / --fillpct) in style. */
export type Vars = CSSProperties & Record<`--${string}`, string | number>;

/* ---------------- text ---------------- */
export function MicroLabel({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  return <span className={cn("microlabel", className)} style={style}>{children}</span>;
}
export function Annotation({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  return <span className={cn("annotation", className)} style={style}>{children}</span>;
}
/** The brand mark: the marginal-rate spectrum as a hairline rule. */
export function StrataLine({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div className={cn("strata-line", className)} style={style} />;
}
export function Hairline({ className }: { className?: string }) {
  return <hr className={cn("hairline", className)} />;
}
export function Dot({ live, tone, className }: { live?: boolean; tone?: Tone; className?: string }) {
  return (
    <span
      className={cn("dot", live && "dot-live", className)}
      style={!live && tone ? { background: `var(--${tone})` } : undefined}
    />
  );
}

/* ---------------- money ----------------
   The PLAIN figure: tabular, optionally toned. For an interrogable figure
   ("no naked numbers") use <ProvFigure> from ./prov, which wraps this. */
export function Money({
  cents,
  tone,
  className,
  signed,
}: {
  cents: number;
  tone?: Tone;
  className?: string;
  /** show an explicit +/− (delta chips); default formats magnitude only */
  signed?: boolean;
}) {
  const sign = signed ? (cents > 0 ? "+" : cents < 0 ? "−" : "") : "";
  const body = centsToUSD(Math.abs(cents));
  return <span className={cn("money fig", tone && `tone-${tone}`, className)}>{sign}{body}</span>;
}
/** A monospaced figure that isn't dollars (rates, counts, ids). */
export function Fig({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("fig", className)}>{children}</span>;
}

/* ---------------- panel ---------------- */
export function Panel({ className, children, ...rest }: ComponentProps<"div">) {
  return <div className={cn("panel", className)} {...rest}>{children}</div>;
}
export function PanelHead({
  children,
  className,
  ...rest
}: ComponentProps<"div">) {
  return <div className={cn("panel-head", className)} {...rest}>{children}</div>;
}

/* ---------------- env (per-client / per-agent hue scope) ----------------
   Sets --chue / --ahue on a wrapper so descendant avatars + accents inherit
   the right hue (§2). Wrap a case file in <Env clientId> ; a staff card in
   <Env agent>. */
export function Env({
  clientId,
  hue,
  agent,
  className,
  style,
  children,
  as: As = "div",
}: {
  clientId?: string;
  hue?: string;
  agent?: AgentKey;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
  as?: "div" | "section" | "span";
}) {
  const vars: Vars = { ...(style as Vars) };
  const chue = hue ?? (clientId ? hueForClient(clientId) : undefined);
  if (chue) vars["--chue"] = chue;
  if (agent) vars["--ahue"] = AGENT_HUES[agent];
  return <As className={className} style={vars}>{children}</As>;
}

/* ---------------- chip ---------------- */
type ChipTone = "save" | "cost" | "cliff" | "agent" | "seal" | "neutral";
export function Chip({
  tone = "neutral",
  icon,
  className,
  style,
  children,
  href,
  onClick,
}: {
  tone?: ChipTone;
  icon?: ReactNode;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
  href?: string;
  onClick?: () => void;
}) {
  const cls = cn("chip", tone !== "neutral" && tone, className);
  const inner = (
    <>
      {icon}
      {children}
    </>
  );
  if (href) return <a className={cls} style={style} href={href}>{inner}</a>;
  if (onClick) return <button type="button" className={cls} style={style} onClick={onClick}>{inner}</button>;
  return <span className={cls} style={style}>{inner}</span>;
}

/* ---------------- stamp ----------------
   verified (engine-checked) · draft · signed (gold) · flag (needs attention) */
type StampKind = "verified" | "draft" | "signed" | "flag";
export function Stamp({
  kind,
  fresh,
  className,
  children,
}: {
  kind: StampKind;
  fresh?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return <span className={cn("stamp", `stamp-${kind}`, fresh && "fresh", className)}>{children}</span>;
}

/* ---------------- stage (engagement pipeline node) ---------------- */
type StageState = "todo" | "on" | "done" | "sealed";
export function Stage({ state = "todo", children }: { state?: StageState; children: ReactNode }) {
  return <span className={cn("stage", state !== "todo" && state)}>{children}</span>;
}

/* ---------------- buttons ----------------
   v3 variants (distinct from components/ui.tsx's legacy Button, which existing
   v1 routes still use). One filled `ink` primary per screen; `seal` only on
   sign/seal actions (§2). */
type BtnVariant = "ink" | "ghost" | "seal" | "agent";
export function Button({
  variant = "ghost",
  icon,
  className,
  children,
  ...rest
}: ComponentProps<"button"> & { variant?: BtnVariant; icon?: ReactNode }) {
  return (
    <button className={cn("btn", `btn-${variant}`, className)} {...rest}>
      {icon}
      {children}
    </button>
  );
}
export function MiniButton({
  go,
  seal,
  className,
  children,
  href,
  ...rest
}: ComponentProps<"button"> & { go?: boolean; seal?: boolean; href?: string }) {
  const cls = cn("mini-btn", go && "go", seal && "seal", className);
  if (href) return <a className={cls} href={href}>{children}</a>;
  return <button className={cls} {...rest}>{children}</button>;
}

/* ---------------- avatars ----------------
   Cavatar (client, round, --chue) · Aavatar (agent, rounded square, --ahue,
   presence dot). Initials derived; hue from Env scope or explicit prop. */
function initials(name: string): string {
  const parts = name.trim().split(/[\s&]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
export function Cavatar({ name, hue, className }: { name: string; hue?: string; className?: string }) {
  return (
    <span className={cn("cavatar", className)} style={hue ? ({ "--chue": hue } as Vars) : undefined}>
      {initials(name)}
    </span>
  );
}
export function Aavatar({
  name,
  agent,
  hue,
  idle,
  className,
}: {
  name: string;
  agent?: AgentKey;
  hue?: string;
  idle?: boolean;
  className?: string;
}) {
  const ahue = hue ?? (agent ? AGENT_HUES[agent] : undefined);
  return (
    <span className={cn("aavatar", className)} style={ahue ? ({ "--ahue": ahue } as Vars) : undefined}>
      {initials(name)}
      <span className={cn("st", idle && "idle")} />
    </span>
  );
}

/* ---------------- working dots (agent is running) ---------------- */
export function WorkingDots({ className }: { className?: string }) {
  return (
    <span className={cn("w-dots", className)} aria-label="working">
      <span /><span /><span />
    </span>
  );
}
