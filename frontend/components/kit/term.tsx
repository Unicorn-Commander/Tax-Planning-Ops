"use client";

// kit/term.tsx — the global "what's this?" on-ramp affordance (§0.7).
// Any expert TERM gets a dotted teal underline and reveals a one-sentence plain
// gloss on hover/tap. Distinct from ProvFigure (which explains how a NUMBER was
// computed); Term explains what a CONCEPT means. A CPA reads past it; a newcomer
// is never lost. Plain-language is the DEFAULT label everywhere; this is how the
// expert term stays one tap away.

import { useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { GLOSS } from "./tokens";

export function Term({
  k,
  term,
  gloss,
  children,
  className,
}: {
  /** a key into the canonical GLOSS map (§0.7) */
  k?: keyof typeof GLOSS;
  /** or supply your own term label + gloss inline */
  term?: string;
  gloss?: string;
  /** the inline text to underline (defaults to the term label) */
  children?: ReactNode;
  className?: string;
}) {
  const entry = k ? GLOSS[k] : undefined;
  const label = term ?? entry?.term ?? "";
  const body = gloss ?? entry?.gloss ?? "";
  const [open, setOpen] = useState(false);
  const [flip, setFlip] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  function reveal() {
    // flip below the term when it sits near the top of the viewport
    const top = ref.current?.getBoundingClientRect().top ?? 999;
    setFlip(top < 170);
    setOpen(true);
  }

  return (
    <span
      ref={ref}
      className={cn("term", open && "open", className)}
      tabIndex={0}
      role="button"
      aria-label={`What's this: ${label}`}
      onMouseEnter={reveal}
      onMouseLeave={() => setOpen(false)}
      onFocus={reveal}
      onBlur={() => setOpen(false)}
      onClick={(e) => {
        e.stopPropagation();
        if (open) setOpen(false);
        else reveal();
      }}
    >
      {children ?? label}
      <span className={cn("gloss-pop", flip && "flip")} role="tooltip">
        <span className="gt">{label}</span>
        {body}
      </span>
    </span>
  );
}
