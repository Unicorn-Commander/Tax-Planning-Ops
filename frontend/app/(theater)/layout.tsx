"use client";

// The THEATER route group (§1) — present mode (13) + marketing. A separate
// group so it ESCAPES the workbench chrome (no topbar, no file nav). Always
// dark via body.theater (independent of the data-theme toggle); the cream paper
// plates read as lit screens in a meeting. Documents stay paper.

import { useEffect } from "react";

export default function TheaterLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    document.body.classList.add("theater");
    return () => document.body.classList.remove("theater");
  }, []);
  return <div className="min-h-screen">{children}</div>;
}
