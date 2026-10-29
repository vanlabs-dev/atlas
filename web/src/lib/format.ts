// Number and date text for the boards. Missing values print as a dash,
// zeros as zeros, and changes carry their sign in the text.

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function signed(v: number | null | undefined, digits = 0, unit = ""): string {
  if (v === null || v === undefined) return "-";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${num(Math.abs(v), digits)}${unit}`;
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** What the miner-code scan found, in words. */
export const VERDICT: Record<string, string> = {
  possible: "Runs on a CPU",
  "needs-gpu": "Needs a GPU",
  unknown: "Not readable",
};

export function verdict(v: string | null): string {
  return v ? (VERDICT[v] ?? v) : "-";
}
