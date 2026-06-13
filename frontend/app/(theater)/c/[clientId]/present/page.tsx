"use client";

// Surface 13 — PRESENT (theater). A full-screen paper deck rendered FROM the
// signed memo: cover (headline number net of fee), simplified position (3 marks
// max, zero jargon), the moves (top 3 accepted findings), keep/cost plate +
// calendar + provenance footline. Arrow keys page; F fullscreen. A pure view
// over signed-memo + plan data — so it cannot exist until the memo is signed.

import Link from "next/link";
import { use } from "react";
import { ArrowLeft } from "lucide-react";
import { Sheet, MicroLabel } from "@/components/kit";

export default function PresentPage({ params }: { params: Promise<{ clientId: string }> }) {
  const { clientId } = use(params);
  return (
    <div className="grid min-h-screen place-items-center p-8">
      <Sheet className="w-full max-w-[900px] p-12">
        <MicroLabel>Present — meeting mode</MicroLabel>
        <h1 className="mt-3">The deck builds itself from the signed memo.</h1>
        <p className="lede mt-2">
          Cover · simplified position · the moves · keep/cost · calendar — net of fee, zero jargon,
          every plate a view over work you already signed.
        </p>
        <p className="mt-6">
          This surface is a pure renderer over the signed memo + plan (spec §7-13, additive). It
          stays empty until the memorandum is sealed — present mode never invents a number.
        </p>
        <div className="mt-8 border-t border-[var(--p-hairline)] pt-4 font-mono text-[11px] text-[var(--p-ink-3)]">
          file {clientId.slice(0, 8)} · arrow keys page · F fullscreen
        </div>
      </Sheet>
      <Link
        href={`/c/${clientId}/memo`}
        className="mini-btn fixed left-5 top-5 inline-flex items-center gap-1.5"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to the memo
      </Link>
    </div>
  );
}
