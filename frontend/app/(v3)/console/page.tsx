"use client";

// Surface 00 — THE CONSOLE (door 2). The shell is real (it IS the door); the
// streaming run (plan card → engine-call trace → priced questions), the inline
// artifacts, and the GUI↔chat sync are Phase 2 (frontier) over the same engine
// tools the GUI buttons call. No faked streaming here (the AO port's mistake).

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ConsolePane,
  ConsoleMessage,
  DoorsMini,
  Aavatar,
  Chip,
  Panel,
  MicroLabel,
} from "@/components/kit";

const EXAMPLES = [
  "What's my true next-dollar rate?",
  "/scan-book",
  "Draft the memo for Marcus Webb",
  "Compare an S-corp split at $45k vs $60k salary",
];

function ConsoleInner() {
  const params = useSearchParams();
  const seeded = params.get("q");
  const [log, setLog] = useState<{ from: "you" | "them"; text: string }[]>([]);

  useEffect(() => {
    if (seeded) setLog([{ from: "you", text: seeded }, PHASE2_REPLY]);
  }, [seeded]);

  function send(v: string) {
    setLog((l) => [...l, { from: "you", text: v }, PHASE2_REPLY]);
  }

  return (
    <div className="wrap grid gap-5 py-7 lg:grid-cols-[1.4fr_1fr]">
      <ConsolePane
        className="h-[72vh]"
        head={
          <>
            <Aavatar name="Strategist" agent="strategist" />
            <div className="leading-tight">
              <div className="text-[14px] font-semibold">Strategist</div>
              <div className="font-mono text-[11px] text-[var(--g-ink-3)]">propose · you sign</div>
            </div>
            <div className="ml-auto">
              <DoorsMini active="console" />
            </div>
          </>
        }
        onSubmit={send}
      >
        {log.length === 0 ? (
          <ConsoleMessage from="them" avatar={<Aavatar name="Strategist" agent="strategist" />}>
            I work the file; you sign the memo. Ask me anything, or run a command — the same
            engine tools the buttons call. Try one:
            <div className="mt-2.5 flex flex-wrap gap-2">
              {EXAMPLES.map((e) => (
                <Chip key={e} tone="agent" onClick={() => send(e)}>{e}</Chip>
              ))}
            </div>
          </ConsoleMessage>
        ) : (
          log.map((m, i) =>
            m.from === "you" ? (
              <ConsoleMessage key={i} from="you">{m.text}</ConsoleMessage>
            ) : (
              <ConsoleMessage key={i} from="them" avatar={<Aavatar name="Strategist" agent="strategist" />}>
                {m.text}
              </ConsoleMessage>
            ),
          )
        )}
      </ConsolePane>

      <Panel className="h-fit p-5">
        <MicroLabel>the canvas</MicroLabel>
        <p className="mt-2 text-[13.5px] text-[var(--g-ink-2)]">
          The right pane is the workspace the Console acts on — a Position strip, a memo summary,
          a scenario — each produced inline with an &quot;open in full&quot; into its GUI surface.
        </p>
        <ul className="mt-3 space-y-1.5 text-[12.5px] text-[var(--g-ink-3)]">
          <li><b className="tone-agent">[live]</b> strategist / propose-plan / scan-book are the answer engine.</li>
          <li><b className="tone-cost">[additive]</b> the streaming run (plan + call trace + question objects), inline-artifact embedding, GUI↔chat sync, and the real MCP server (shared with ⌘K).</li>
        </ul>
      </Panel>
    </div>
  );
}

const PHASE2_REPLY = {
  from: "them" as const,
  text:
    "Heard. The live streaming run — my plan, the literal engine calls, and any priced question — wires in Phase 2 over the real strategist endpoint; I won't fake a result here.",
};

export default function ConsolePage() {
  return (
    <Suspense fallback={<div className="wrap py-7"><div className="skeleton h-[60vh] w-full" /></div>}>
      <ConsoleInner />
    </Suspense>
  );
}
