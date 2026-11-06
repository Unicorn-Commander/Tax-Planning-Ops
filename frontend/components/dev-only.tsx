"use client";

import type { ReactNode } from "react";

/** Provenance tags ([live], [additive], [fixture], spec cites) stay off customer screens. */
export const SHOW_DEV_LABELS = process.env.NEXT_PUBLIC_TPO_DEV_LABELS === "1";

export function DevOnly({ children }: { children: ReactNode }) {
  if (!SHOW_DEV_LABELS) return null;
  return <>{children}</>;
}
