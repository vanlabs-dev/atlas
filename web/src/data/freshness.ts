// Data age. Pages render the ISO time when they read their data and
// compute the age in the browser, so a cached page does not freeze it.

export const STALE_AFTER_HOURS = 48;

export interface Freshness {
  hours: number;
  stale: boolean;
  label: string;
}

export function freshness(generatedAt: string, now: Date): Freshness {
  const ms = now.getTime() - new Date(generatedAt).getTime();
  const hours = Math.max(0, ms / 3_600_000);
  return { hours, stale: hours > STALE_AFTER_HOURS, label: ageLabel(hours) };
}

function ageLabel(hours: number): string {
  if (hours < 1) return "under an hour ago";
  if (hours < 48) return `${Math.floor(hours)} h ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

/**
 * Stale label for the server HTML, from the time the page read its data
 * (change: supabase-data-layer). The server copy is at most one refresh
 * behind; the browser recomputes the label on load.
 */
export function staleAtRead(generatedAt: string, readAt: string | undefined): boolean {
  if (!readAt || Number.isNaN(Date.parse(readAt))) return false;
  return freshness(generatedAt, new Date(readAt)).stale;
}

/**
 * How a page states its data age.
 * read: server HTML and first paint. No age text; the stale label is judged at the time the page read its data.
 * live: in the browser. The age is counted to the minute, and the stale label follows the visitor's clock.
 */
export interface DataAgeView {
  clock: "read" | "live";
  status: "fresh" | "stale";
  /** "6 days ago"; null while the clock is "read". */
  label: string | null;
}

export function dataAge(generatedAt: string, readAt: string | undefined, now: Date | null): DataAgeView {
  if (!now) return { clock: "read", status: staleAtRead(generatedAt, readAt) ? "stale" : "fresh", label: null };
  const f = freshness(generatedAt, now);
  return { clock: "live", status: f.stale ? "stale" : "fresh", label: f.label };
}
