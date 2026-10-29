// Data age. Pages render the ISO time at build and compute the age in the
// browser, so a static page does not freeze it.

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
