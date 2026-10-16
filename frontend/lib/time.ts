export const BUSINESS_TIME_ZONE = "America/New_York";

const DATE_ONLY_PREFIX = /^(\d{4})-(\d{2})-(\d{2})(?:$|T)/;

/**
 * Format a calendar date without interpreting it as a viewer-local instant.
 * This accepts both YYYY-MM-DD values and UTC-midnight ISO values used by the
 * backend for date-only task deadlines.
 */
export function formatDateOnly(
  value: string | null | undefined,
  options: { includeYear?: boolean } = {},
): string {
  if (!value) return "—";

  const match = DATE_ONLY_PREFIX.exec(value);
  if (!match) return value;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    ...(options.includeYear === false ? {} : { year: "numeric" }),
  }).format(date);
}

/** Return the current calendar date in the business timezone. */
export function businessDate(at: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BUSINESS_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(at);
  const year = parts.find((part) => part.type === "year")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  const day = parts.find((part) => part.type === "day")?.value ?? "";
  return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
}

/** Return the statutory quarter for a business-zone instant. */
export function currentBusinessQuarter(at: Date = new Date()): number {
  const month = Number(businessDate(at).slice(5, 7));
  if (month <= 4) return 1;
  if (month <= 6) return 2;
  if (month <= 9) return 3;
  return 4;
}
