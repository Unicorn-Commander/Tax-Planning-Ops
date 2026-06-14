"use client";

// Surface 15 — THE FRONT DOOR (the on-ramp, §0.7). The root for a workspace
// with no data: calm, centered, jargon-free. One obvious action (bring in last
// year's 1040 — the universal sub-minute first-value loop) + the console at
// rest. The posture toggle sets the shell; it is asked once.

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Upload, MessageSquare, ArrowRight, HelpCircle, Check } from "lucide-react";
import { Omnibar, Panel, MicroLabel, StrataLine, Chip } from "@/components/kit";
import { cn } from "@/lib/cn";

const POSTURES = [
  { key: "solo", label: "For myself", sub: "an individual" },
  { key: "company", label: "My business", sub: "a company / family office" },
  { key: "firm", label: "My clients", sub: "a CPA / advisory firm" },
] as const;

type PostureKey = (typeof POSTURES)[number]["key"];

// The entity-type step (static design content, mirrors the backend catalog's
// ENTITY_TYPES keys; the intake page fetches the live checklist from
// GET /intake/document-checklist?entity_type=<key>). Each carries a one-line
// plain-language description so a non-expert can self-identify; `not_sure` shows
// the descriptions as a short explainer instead of guessing.
const ENTITY_OPTIONS = [
  {
    key: "individual",
    label: "Just me / my household",
    sub: "personal taxes — a Form 1040",
    plain: "You file a personal return — wages, investments, maybe a rental, but no business of your own.",
  },
  {
    key: "sole_prop",
    label: "A business I run solo",
    sub: "sole proprietor / single-member LLC",
    plain: "You run a business by yourself and report it on Schedule C of your personal return.",
  },
  {
    key: "partnership",
    label: "A business with partners",
    sub: "partnership / multi-member LLC",
    plain: "Two or more owners share a business that files Form 1065 and issues each owner a K-1.",
  },
  {
    key: "s_corp",
    label: "An S corporation",
    sub: "Form 1120-S + owner salary",
    plain: "A corporation or LLC that elected S status, pays owners a salary, and passes profit through on K-1s.",
  },
  {
    key: "c_corp",
    label: "A C corporation",
    sub: "Form 1120 — pays its own tax",
    plain: "A corporation that files and pays its own tax, separate from your personal return.",
  },
  {
    key: "not_sure",
    label: "I'm not sure",
    sub: "show me the difference",
    plain: "No problem — here's the plain-English version of each so you can pick the one that fits.",
  },
] as const;

type EntityOption = (typeof ENTITY_OPTIONS)[number];
type EntityKey = EntityOption["key"];

// Which entity choices to lead with for a posture. "For myself" leads with the
// individual; a business/firm keeps the default order. We never hide a choice
// (you might be a solo founder), only reorder — calm, not restrictive.
function entitiesForPosture(posture: PostureKey): readonly EntityOption[] {
  if (posture !== "solo") return ENTITY_OPTIONS;
  const order: EntityKey[] = ["individual", "sole_prop", "s_corp", "partnership", "c_corp", "not_sure"];
  return [...ENTITY_OPTIONS].sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
}

const ASK_EXAMPLES = [
  "How much could I save this year?",
  "What happens if I convert $40k to Roth?",
  "Should my business be an S-corp?",
];

export default function StartPage() {
  const [posture, setPosture] = useState<PostureKey>("solo");
  const [entity, setEntity] = useState<EntityKey | null>(null);
  const router = useRouter();

  const entityOptions = useMemo(() => entitiesForPosture(posture), [posture]);
  // The chosen entity (skip the not_sure affordance — it has no checklist).
  const chosenEntity = entity && entity !== "not_sure" ? entity : null;
  const intakeHref = chosenEntity ? `/intake?entity=${chosenEntity}` : "/intake";
  const deskHref = chosenEntity ? `/desk?entity=${chosenEntity}` : "/desk";
  const notSurePicked = entity === "not_sure";

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

      {/* entity step — what kind of taxes? sets the document checklist. Calm,
          plain-language, optional ("Not sure" explains rather than guesses). */}
      <div className="mt-7">
        <div className="mb-2.5 text-center">
          <MicroLabel>What kind of taxes are we planning?</MicroLabel>
          <p className="mt-1 text-[12.5px] text-[var(--g-ink-3)]">
            This tailors the short list of documents we&apos;ll need. You can change it anytime.
          </p>
        </div>
        <div className="mx-auto grid max-w-[760px] grid-cols-2 gap-2 sm:grid-cols-3">
          {entityOptions.map((e) => {
            const sel = entity === e.key;
            const isNotSure = e.key === "not_sure";
            return (
              <button
                key={e.key}
                type="button"
                onClick={() => setEntity(e.key)}
                aria-pressed={sel}
                className={cn(
                  "flex items-center gap-2.5 rounded-[12px] border px-3.5 py-2.5 text-left transition-colors",
                  sel
                    ? "border-[color-mix(in_srgb,var(--agent)_45%,transparent)] bg-[var(--agent-soft)]"
                    : "border-[var(--g-hairline)] bg-[var(--g-surface)] hover:bg-[var(--g-bg-2)]",
                )}
              >
                <span
                  className={cn(
                    "grid h-5 w-5 flex-none place-items-center rounded-full border-[1.5px] transition-colors",
                    sel ? "border-[var(--agent)] bg-[var(--agent)] text-white" : "border-[var(--g-hairline)] text-transparent",
                  )}
                >
                  {isNotSure ? <HelpCircle className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0">
                  <span className={cn("block text-[13px] font-semibold leading-tight", sel && "tone-agent")}>{e.label}</span>
                  <span className="block text-[11px] leading-tight text-[var(--g-ink-3)]">{e.sub}</span>
                </span>
              </button>
            );
          })}
        </div>

        {/* "Not sure" explainer — the plain-English version of each choice */}
        {notSurePicked && (
          <div className="mx-auto mt-3 max-w-[760px] rounded-[12px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] p-4">
            <p className="mb-2.5 text-[12.5px] text-[var(--g-ink-2)]">
              In plain English — pick whichever sounds like you:
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {ENTITY_OPTIONS.filter((e) => e.key !== "not_sure").map((e) => (
                <button
                  key={e.key}
                  type="button"
                  onClick={() => setEntity(e.key)}
                  className="rounded-[10px] border border-[var(--g-hairline-soft)] bg-[var(--g-surface)] px-3.5 py-2.5 text-left transition-colors hover:border-[color-mix(in_srgb,var(--agent)_45%,transparent)] hover:bg-[var(--agent-soft)]"
                >
                  <div className="text-[12.5px] font-semibold text-[var(--g-ink)]">{e.label}</div>
                  <div className="mt-0.5 text-[11.5px] leading-snug text-[var(--g-ink-3)]">{e.plain}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* confirmation of a real choice — reassures + previews the next step */}
        {chosenEntity && (
          <p className="mt-3 text-center text-[12.5px] text-[var(--g-ink-2)]">
            <Check className="mr-1 inline h-3.5 w-3.5 text-[var(--save)]" />
            Good — we&apos;ll show you the documents a{" "}
            <b className="text-[var(--g-ink)]">
              {ENTITY_OPTIONS.find((e) => e.key === chosenEntity)?.label.toLowerCase()}
            </b>{" "}
            plan needs.
          </p>
        )}
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
            onClick={() => router.push(deskHref)}
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
        <Link href={intakeHref} className="text-[var(--g-ink-2)] underline-offset-4 hover:underline">
          {chosenEntity ? "See what we'll need & answer a few questions" : "Answer 6 questions instead"}
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
