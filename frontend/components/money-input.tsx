"use client";

import { useState } from "react";

import { centsToDollarString, dollarsToCents } from "@/lib/format";

/**
 * Dollar-denominated money input. The advisor types dollars (e.g. 50000 =
 * $50,000); the parent receives integer cents. Prevents the cents/dollars
 * data-entry trap where a plausible "50000" silently became $500.
 */
export function MoneyInput({
  valueCents,
  onChangeCents,
  onBlurCents,
  placeholder = "0.00",
  className,
  id,
}: {
  valueCents: number | null;
  onChangeCents?: (cents: number | null) => void;
  /** Fired once on blur — use for network commits (e.g. PATCH an override). */
  onBlurCents?: (cents: number | null) => void;
  placeholder?: string;
  className?: string;
  id?: string;
}) {
  const [text, setText] = useState(() => centsToDollarString(valueCents));

  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--muted)]">
        $
      </span>
      <input
        id={id}
        inputMode="decimal"
        value={text}
        placeholder={placeholder}
        onChange={(event) => {
          setText(event.target.value);
          onChangeCents?.(dollarsToCents(event.target.value));
        }}
        onBlur={(event) => onBlurCents?.(dollarsToCents(event.target.value))}
        className={className ?? "h-10 w-full rounded-md border border-[var(--line)] pl-6 pr-3 text-sm"}
      />
    </div>
  );
}
