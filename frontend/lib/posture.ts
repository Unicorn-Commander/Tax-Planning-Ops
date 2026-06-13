"use client";

// lib/posture.ts — the posture resolver (§0.5). One engine, two postures:
//   solo/company → Your Plan (14) as home, shell dissolves
//   firm         → The Desk (01) as home, firm shell mounts
// gated on `fileCount > 1 || kind === 'firm'`.
//
// Real detection is [additive] (the workspace needs fileCount/kind from the
// API — spec §7-14). Until that lands we default to FIRM (the demo workspace is
// Northstar, a firm with a book) and honor a localStorage override so both
// shells are testable: localStorage.setItem('tpo-posture','solo').

import { useEffect, useState } from "react";

export type Posture = "solo" | "firm";

export function readPostureOverride(): Posture | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem("tpo-posture");
  return v === "solo" || v === "firm" ? v : null;
}

/** TODO(integration: workspace.fileCount / workspace.kind) — see spec §7-14. */
export function resolvePosture(fileCount?: number, kind?: string): Posture {
  if (kind === "firm") return "firm";
  if (typeof fileCount === "number") return fileCount > 1 ? "firm" : "solo";
  return "firm";
}

/** The home route for a posture. */
export function homeFor(posture: Posture): string {
  return posture === "firm" ? "/desk" : "/home";
}

export function usePosture(): Posture {
  // Default firm on first paint (matches the seeded demo); apply any override
  // after mount to avoid an SSR/CSR mismatch.
  const [posture, setPosture] = useState<Posture>("firm");
  useEffect(() => {
    const o = readPostureOverride();
    if (o) setPosture(o);
  }, []);
  return posture;
}
