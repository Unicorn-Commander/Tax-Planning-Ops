"use client";

// Surface 15 — THE FRONT DOOR (the on-ramp, §0.7). The root for a workspace
// with no data: calm, centered, jargon-free. One obvious action (bring in last
// year's 1040 — the universal sub-minute first-value loop) + the console at
// rest. The posture toggle sets the shell; it is asked once.

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Upload, MessageSquare, ArrowRight } from "lucide-react";
import { Omnibar, Panel, MicroLabel, StrataLine, Chip } from "@/components/kit";
import { cn } from "@/lib/cn";

const POSTURES = [
  { key: "solo", label: "For myself", sub: "an individual" },
  { key: "company", label: "My business", sub: "a company / family office" },
  { key: "firm", label: "My clients", sub: "a CPA / advisory firm" },
] as const;

const ASK_EXAMPLES = [
  "How much could I save this year?",
  "What happens if I convert $40k to Roth?",
  "Should my business be an S-corp?",
];

export default function StartPage() {
  const [posture, setPosture] = useState<(typeof POSTURES)[number]["key"]>("solo");
  const router = useRouter();

  return (
    <div className="wrap max-w-[920px] py-16">
      {/* hero */}
      <div className="text-center">
        <div className="mx-auto mb-5 inline-block">
          <StrataLine className="mx-auto mb-3 w-24" />
          <MicroLabel>Tax-Planning-Ops</MicroLabel>
        </div>
        <h1 className="text-[40px] font-bold leading-[1.08] tracking-[-0.02em]">
          Let&apos;s find what your taxes are leaving on the table.
        </h1>
        <p className="mx-auto mt-3 max-w-[560px] text-[16px] leading-relaxed text-[var(--g-ink-2)]">
          Bring in last year&apos;s return and you&apos;ll see your position in plain English in
          about a minute — no jargon, every number traceable to the engine that computed it.
        </p>
      </div>

      {/* posture toggle — sets the shell, asked once */}
      <div className="mt-8 flex justify-center gap-2">
        {POSTURES.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => setPosture(p.key)}
            className={cn(
              "rounded-[12px] border px-4 py-2.5 text-left transition-colors",
              posture === p.key
                ? "border-[color-mix(in_srgb,var(--agent)_45%,transparent)] bg-[var(--agent-soft)]"
                : "border-[var(--g-hairline)] bg-[var(--g-surface)] hover:bg-[var(--g-bg-2)]",
            )}
          >
            <div className={cn("text-[13.5px] font-semibold", posture === p.key && "tone-agent")}>{p.label}</div>
            <div className="text-[11.5px] text-[var(--g-ink-3)]">{p.sub}</div>
          </button>
        ))}
      </div>

      {/* the two co-equal doors */}
      <div className="mt-7 grid gap-4 md:grid-cols-2">
        {/* door 1: bring in a 1040 */}
        <Panel className="flex flex-col p-6">
          <div className="flex h-11 w-11 items-center justify-center rounded-[12px] bg-[var(--agent-soft)] tone-agent">
            <Upload className="h-5 w-5" />
          </div>
          <h2 className="mt-3 text-[17px] font-semibold">Drop in last year&apos;s 1040</h2>
          <p className="mt-1 flex-1 text-[13.5px] text-[var(--g-ink-2)]">
            We read it, check our math against it, and show you the plan. PDF or photo.
          </p>
          <button
            type="button"
            onClick={() => router.push("/desk")}
            className="btn btn-ink mt-4 justify-center"
          >
            Choose a file <ArrowRight className="h-4 w-4" />
          </button>
        </Panel>

        {/* door 2: just ask */}
        <Panel className="flex flex-col p-6">
          <div className="flex h-11 w-11 items-center justify-center rounded-[12px] bg-[var(--agent-soft)] tone-agent">
            <MessageSquare className="h-5 w-5" />
          </div>
          <h2 className="mt-3 text-[17px] font-semibold">Or just ask</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">
            No return handy? Tell the strategist what you&apos;re trying to figure out.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {ASK_EXAMPLES.map((e) => (
              <Chip key={e} tone="agent" onClick={() => router.push(`/console?q=${encodeURIComponent(e)}`)}>
                {e}
              </Chip>
            ))}
          </div>
        </Panel>
      </div>

      {/* what happens next — kills first-run anxiety */}
      <div className="mt-8 grid gap-3 sm:grid-cols-3">
        {[
          ["1", "You bring it in", "Drop a 1040, or answer a few questions."],
          ["2", "We read & check", "~40 seconds: extract, then recompute every line to verify."],
          ["3", "Your plain plan", "Where you stand, and where you could do better — in plain words."],
        ].map(([n, t, b]) => (
          <div key={n} className="rounded-[12px] border border-[var(--g-hairline-soft)] bg-[var(--g-bg-2)] p-4">
            <div className="fig text-[var(--g-ink-3)]">{n}</div>
            <div className="mt-1 text-[13.5px] font-semibold">{t}</div>
            <div className="mt-0.5 text-[12.5px] text-[var(--g-ink-3)]">{b}</div>
          </div>
        ))}
      </div>

      {/* quiet paths */}
      <div className="mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[13px]">
        <Link href="/intake" className="text-[var(--g-ink-2)] underline-offset-4 hover:underline">
          Answer 6 questions instead
        </Link>
        <Link href="/desk" className="text-[var(--g-ink-2)] underline-offset-4 hover:underline">
          Explore a demo
        </Link>
        <Link href="/console" className="text-[var(--g-ink-2)] underline-offset-4 hover:underline">
          Open the console
        </Link>
      </div>

      <div className="mx-auto mt-10 max-w-[560px]">
        <Omnibar placeholder="or type what you're trying to figure out…" />
      </div>
    </div>
  );
}
