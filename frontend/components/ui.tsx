"use client";

import type { ComponentProps, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export { MoneyInput } from "@/components/money-input";

/* ---------------- Card ---------------- */
export function Card({ className, children, ...rest }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b border-line-2 px-5 py-4", className)}>
      <div>
        <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
        {subtitle ? <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

/* ---------------- Button ---------------- */
type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-primary text-white hover:bg-primary-strong shadow-[0_1px_2px_rgba(79,70,229,0.4),0_6px_18px_rgba(79,70,229,0.25)]",
  secondary: "bg-surface text-ink border border-line hover:bg-surface-2",
  ghost: "text-ink-2 hover:bg-surface-2",
  danger: "bg-negative text-white hover:brightness-95",
};

export function Button({
  variant = "primary",
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ComponentProps<"button"> & { variant?: Variant; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      className={cn(
        "inline-flex h-10 items-center justify-center gap-2 rounded-[var(--radius-md)] px-4 text-[13.5px] font-medium",
        "transition-all duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

/* ---------------- Badge ---------------- */
type Tone = "neutral" | "primary" | "positive" | "negative" | "warning";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2 border-line",
  primary: "bg-primary-soft text-primary-strong border-[color-mix(in_srgb,var(--color-primary)_20%,white)]",
  positive: "bg-positive-soft text-positive border-[color-mix(in_srgb,var(--color-positive)_20%,white)]",
  negative: "bg-negative-soft text-negative border-[color-mix(in_srgb,var(--color-negative)_20%,white)]",
  warning: "bg-warning-soft text-warning border-[color-mix(in_srgb,var(--color-warning)_22%,white)]",
};
export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11.5px] font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ---------------- Input ---------------- */
export function Input({ className, ...rest }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] text-ink",
        "placeholder:text-muted outline-none transition-shadow focus:border-primary focus:ring-2 focus:ring-[color-mix(in_srgb,var(--color-primary)_22%,transparent)]",
        className,
      )}
      {...rest}
    />
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12.5px] font-medium text-ink-2">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[12px] text-muted">{hint}</span> : null}
    </label>
  );
}

/* ---------------- Stat ---------------- */
export function Stat({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] font-medium uppercase tracking-wide text-muted">{label}</span>
        {icon ? (
          <span className={cn("flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)]", tone ? TONES[tone] : "bg-primary-soft text-primary")}>
            {icon}
          </span>
        ) : null}
      </div>
      <div className="mt-3 text-[28px] font-semibold leading-none tracking-tight text-ink tabular">{value}</div>
      {sub ? <div className="mt-2 text-[13px] text-muted">{sub}</div> : null}
    </Card>
  );
}

/* ---------------- Skeleton / Empty ---------------- */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-[var(--radius-md)]", className)} />;
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed border-line bg-surface-2/50 px-6 py-14 text-center">
      {icon ? <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft text-primary">{icon}</div> : null}
      <p className="text-[15px] font-semibold text-ink">{title}</p>
      {body ? <p className="mt-1 max-w-sm text-[13.5px] text-muted">{body}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/* ---------------- PageHeader ---------------- */
export function PageHeader({
  title,
  eyebrow,
  subtitle,
  actions,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow ? <div className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-primary">{eyebrow}</div> : null}
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
        {subtitle ? <p className="mt-1 text-[14px] text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* ---------------- Meter (rate bar) ---------------- */
export function Meter({ value, max = 0.37, tone = "primary" }: { value: number; max?: number; tone?: Tone }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  const bar = {
    primary: "bg-primary",
    positive: "bg-positive",
    negative: "bg-negative",
    warning: "bg-warning",
    neutral: "bg-ink-2",
  }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line-2">
      <div className={cn("h-full rounded-full transition-all", bar)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/* ---------------- Disclaimer ---------------- */
export function Disclaimer({ className }: { className?: string }) {
  return (
    <p className={cn("text-[12px] leading-relaxed text-muted", className)}>
      Planning estimate only — not a filed tax return and not tax advice. Figures are projections based
      on advisor-entered assumptions and editable bracket tables.
    </p>
  );
}
