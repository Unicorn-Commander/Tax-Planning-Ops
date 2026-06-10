// Money lives as integer cents on the wire; humans type and read dollars.

export function centsToUSD(cents: number | null | undefined): string {
  return ((cents ?? 0) / 100).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/** Parse a free-form dollar string ("$50,000", "50000.50") to integer cents. */
export function dollarsToCents(input: string): number | null {
  const cleaned = input.replace(/[$,\s]/g, "");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return Math.round(value * 100);
}

export function centsToDollarString(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return String(cents / 100);
}

export function percent(rate: number | string | null | undefined): string {
  const n = typeof rate === "string" ? Number(rate) : (rate ?? 0);
  return `${(n * 100).toFixed(1)}%`;
}
