"use client";

// kit/console.tsx — DOOR 2 (§0.6). The Console is a first-class conversation/
// command surface over the SAME engine tools the GUI buttons call (no wrappers).
// These are the shell + the run-theater pieces; the streaming/sync wiring is
// Phase 2 (frontier). The Omnibar is this same console, collapsed, on every
// other surface.

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { centsToUSD } from "@/lib/format";

/* ---- the literal engine-call trace (§6.1 / §7-06) ---- */
export function EngineCallRow({
  tool,
  result,
  tone,
  running,
  ok,
}: {
  tool: string;
  result?: ReactNode;
  tone?: "save" | "cliff";
  running?: boolean;
  ok?: boolean;
}) {
  return (
    <div className={cn("call", running && "running")}>
      <span className="glyph">∑</span>
      <code>{tool}</code>
      {result !== undefined ? <span className={cn("res", tone)}>{result}</span> : null}
      {ok ? <span className="ok">✓</span> : null}
    </div>
  );
}

/* ---- plan-before-run (§6.6): the editable plan card streamed first ---- */
export function PlanCard({
  steps,
  autoSeconds = 30,
  onHold,
  onProceed,
  className,
}: {
  steps: ReactNode[];
  autoSeconds?: number;
  onHold?: () => void;
  onProceed?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("panel", className)}>
      <div className="panel-head">
        <span className="microlabel">the plan</span>
        <span className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]">
          auto-proceeds in {autoSeconds}s
        </span>
      </div>
      <ol className="m-0 list-none p-2">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-3 px-3 py-2 text-[13px]">
            <span className="fig flex-none text-[var(--g-ink-3)]">{i + 1}</span>
            <span>{s}</span>
          </li>
        ))}
      </ol>
      <div className="flex items-center gap-2 border-t border-[var(--g-hairline-soft)] px-3 py-2.5">
        <button type="button" className="mini-btn" onClick={onHold}>Hold for my review</button>
        <button type="button" className="mini-btn go ml-auto" onClick={onProceed}>Proceed</button>
      </div>
    </div>
  );
}

/* ---- pause-and-ask: ambiguity becomes a PRICED question (§6.5) ---- */
export function PricedQuestion({
  worthCents,
  question,
  options,
  className,
}: {
  worthCents: number;
  question: ReactNode;
  options: { label: ReactNode; onPick?: () => void }[];
  className?: string;
}) {
  return (
    <div className={cn("panel border-l-2 border-l-[var(--cost)]", className)}>
      <div className="px-4 pt-3">
        <span className="microlabel tone-cost">worth {centsToUSD(Math.abs(worthCents))} of certainty</span>
        <p className="mt-1.5 mb-3 text-[14px] font-medium">{question}</p>
        <div className="flex flex-wrap gap-2 pb-3">
          {options.map((o, i) => (
            <button key={i} type="button" className="mini-btn" onClick={o.onPick}>{o.label}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---- a conversation bubble ---- */
export function ConsoleMessage({ from, avatar, children }: { from: "you" | "them"; avatar?: ReactNode; children: ReactNode }) {
  if (from === "you") return <div className="msg you">{children}</div>;
  return (
    <div className="msg them">
      {avatar ? <div className="flex-none">{avatar}</div> : null}
      <div className="bubble-c">{children}</div>
    </div>
  );
}

/* ---- the three-doors badge (makes the no-wrappers point explicit) ---- */
export function DoorsMini({ active = "console" }: { active?: "gui" | "console" | "mcp" }) {
  return (
    <span className="doors-mini" title="One engine, three doors">
      <span className={cn(active === "gui" && "on")}>GUI</span>
      <span className={cn(active === "console" && "on")}>CONSOLE</span>
      <span className={cn(active === "mcp" && "on")}>MCP·API</span>
    </span>
  );
}

/* ---- a controlled composer (shared by ConsolePane + Omnibar) ---- */
function Composer({
  value,
  onChange,
  onSubmit,
  placeholder = "Ask the strategist, or type a command (/scan-book, /draft-memo)…",
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  function submit(e: FormEvent) {
    e.preventDefault();
    if (value.trim()) onSubmit(value.trim());
  }
  return (
    <form className="composer" onSubmit={submit}>
      <div className="box">
        <input
          className="flex-1 border-0 bg-transparent text-[var(--g-ink)] outline-none placeholder:text-[var(--g-ink-3)]"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoFocus={autoFocus}
          aria-label="console input"
        />
        <button type="submit" className="send inline-flex items-center gap-1" aria-label="send">
          <ArrowUp className="h-3.5 w-3.5" />
        </button>
      </div>
    </form>
  );
}

/**
 * The Console shell (door 2). Surfaces fill `head` (strategist identity, the
 * autonomy chip, DoorsMini) and `children` (the message stream / artifacts);
 * Phase 2 wires the streaming run + GUI↔chat sync.
 */
export function ConsolePane({
  head,
  children,
  onSubmit,
  placeholder,
  className,
}: {
  head?: ReactNode;
  children?: ReactNode;
  onSubmit?: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [value, setValue] = useState("");
  const router = useRouter();
  return (
    <div className={cn("console", className)}>
      {head ? <div className="console-head">{head}</div> : null}
      <div className="msgs flex-1 overflow-auto">{children}</div>
      <Composer
        value={value}
        onChange={setValue}
        placeholder={placeholder}
        onSubmit={(v) => {
          setValue("");
          if (onSubmit) onSubmit(v);
          else router.push(`/console?q=${encodeURIComponent(v)}`);
        }}
      />
    </div>
  );
}

/**
 * The Omnibar — the collapsed Console present on every surface (§0.6). Submitting
 * routes to /console with the query by default (or calls onSubmit to act in-place).
 */
export function Omnibar({
  onSubmit,
  placeholder = "Ask the strategist, or ⌘K for actions…",
  className,
}: {
  onSubmit?: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [value, setValue] = useState("");
  const router = useRouter();
  return (
    <div className={cn("rounded-[var(--radius)] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)]", className)}>
      <Composer
        value={value}
        onChange={setValue}
        placeholder={placeholder}
        onSubmit={(v) => {
          setValue("");
          if (onSubmit) onSubmit(v);
          else router.push(`/console?q=${encodeURIComponent(v)}`);
        }}
      />
    </div>
  );
}
