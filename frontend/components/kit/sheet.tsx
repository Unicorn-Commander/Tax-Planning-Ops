// kit/sheet.tsx — the DOCUMENT (§1, §7-06). The warm cream deliverable that
// floats on the bright bench: memo, plan, present plates. Serif voice,
// letterhead, the gold seal (reserved for SIGNED work only, §0.2). Documents
// stay paper in dark mode (--p-* is never overridden), so a memo reads as a
// cream sheet on a dark desk.

import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { centsToUSD } from "@/lib/format";

/** The sheet surface. `print` makes it page-true for PDF/present reuse (§11). */
export function Sheet({ className, children, ...rest }: ComponentProps<"div">) {
  return (
    <div className={cn("sheet", className)} {...rest}>
      {children}
    </div>
  );
}

/**
 * The letterhead. `firm` MUST be read from branding (admin/branding) — never
 * hardcode "Northstar Tax Advisory" (§8, §11 fix-list #2). Solo/company posture
 * passes a "for your records" variant instead of "prepared for".
 */
export function Letterhead({
  firm,
  docRef,
  className,
}: {
  firm: ReactNode;
  docRef?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("letterhead", className)}>
      <span className="firm">{firm}</span>
      {docRef ? <span className="doc-ref">{docRef}</span> : null}
    </div>
  );
}

/** The gold seal disc — ONLY on finalized, hash-stamped work (§0.2). */
export function SealDisc({ label = "Signed & Sealed", className }: { label?: string; className?: string }) {
  return (
    <span className={cn("seal-disc", className)} aria-hidden>
      {label}
    </span>
  );
}

/**
 * The sign & seal block. Unsigned: a dashed waiting box. Signed: the gold seal,
 * signer, date, hash, audit ref (§7-06). Signing is the climax — the rarest
 * resource — so this is visually the heaviest element on the sheet.
 */
export function SignoffBlock({
  signed,
  signer,
  date,
  hash,
  auditRef,
  children,
  className,
}: {
  signed?: boolean;
  signer?: ReactNode;
  date?: ReactNode;
  hash?: string;
  auditRef?: string;
  /** the action (a Sign & Seal button) when unsigned */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("signoff", className)}>
      {signed ? <SealDisc /> : null}
      <div className="min-w-0 flex-1">
        {signed ? (
          <>
            <div className="font-[var(--font-ui)] text-[13px] font-semibold text-[var(--p-ink)]">
              Reviewed &amp; signed{signer ? <> — {signer}</> : null}
            </div>
            <div className="mt-1 font-mono text-[11px] text-[var(--p-ink-3)]">
              {date ? <span>{date}</span> : null}
              {hash ? <span className="ml-3">hash {hash}</span> : null}
              {auditRef ? <span className="ml-3">{auditRef}</span> : null}
            </div>
          </>
        ) : (
          <div className="font-[var(--font-ui)] text-[13px] text-[var(--p-ink-2)]">
            Advisor signature required before anything client-facing.
          </div>
        )}
      </div>
      {!signed && children ? <div className="flex-none">{children}</div> : null}
    </div>
  );
}

/** A finding rendered as an exhibit inside the sheet, with an impact figure. */
export function Exhibit({
  no,
  title,
  impactCents,
  impactKind = "save",
  toolbar,
  children,
  className,
}: {
  no: string;
  title: ReactNode;
  impactCents?: number;
  impactKind?: "save" | "cost";
  /** editorial toolbar (Edit / Reorder / Hide / Accept→plan) — REQUIRED before client-facing */
  toolbar?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("exhibit", className)}>
      <div className="x-head">
        <span className="x-no">EXHIBIT {no}</span>
        <span className="font-[var(--font-doc)] text-[16px] font-semibold text-[var(--p-ink)]">{title}</span>
        {impactCents !== undefined ? (
          <span className={cn("x-impact", impactKind)}>
            {impactKind === "save" ? "−" : "+"}
            {centsToUSD(Math.abs(impactCents))}
          </span>
        ) : null}
      </div>
      {children ? <div className="mt-2 text-[14px] leading-relaxed text-[var(--p-ink-2)]">{children}</div> : null}
      {toolbar ? <div className="mt-3 flex items-center gap-2">{toolbar}</div> : null}
    </div>
  );
}
