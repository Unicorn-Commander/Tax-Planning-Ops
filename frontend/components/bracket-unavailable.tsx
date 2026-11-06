"use client";

import Link from "next/link";

/** Shown where the strata chart should be when that year + status has no rows. */
export function BracketUnavailable({
  year,
  filingStatus,
}: {
  year: number | string;
  filingStatus: string;
}) {
  return (
    <p className="text-[13px] text-[var(--g-ink-3)]">
      Bracket set unavailable for {year} {filingStatus}.{" "}
      <Link href="/admin/brackets" className="font-medium text-[var(--agent)] underline underline-offset-2">
        Load the {year} bracket set in Admin → Brackets
      </Link>
      .
    </p>
  );
}
