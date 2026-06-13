"use client";

// The v3 workbench shell. Renders the posture-aware topbar for the firm-shell
// and solo surfaces; the file (/c/:id) routes bring their own FileTopbar (the
// file is the context), so the topbar is suppressed there. Auth + workspace
// context come from the root ClientProviders; theme + the dark-mode toggle are
// global (app/layout.tsx).

import { usePathname } from "next/navigation";
import { V3Topbar } from "./shell";

export default function V3Layout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isFile = pathname.startsWith("/c/");
  return (
    <div className="min-h-screen">
      {isFile ? null : <V3Topbar />}
      <main className="min-w-0">{children}</main>
    </div>
  );
}
