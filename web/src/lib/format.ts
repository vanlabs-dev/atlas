// Number and date text for the boards. Missing values print as a dash,
// zeros as zeros, and changes carry their sign in the text.

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "-";
  return v.toLocaleString("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function signed(v: number | null | undefined, digits = 0, unit = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "-";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${num(Math.abs(v), digits)}${unit}`;
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** A percentage, or a dash with no unit when missing. */
export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "-" : `${num(v, digits)}%`;
}

/** Mean of a list, or null when it is empty. */
export function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

/** Colour for a "what moved" figure only: up in green, down in red. */
export function polarity(v: number | null | undefined): string {
  if (!v) return "";
  return v < 0 ? "text-down" : "text-up";
}
