// Daily commit bins with the activity metric's window rule.
//
// The metric (`compute_activity` in fleet/atlas_fleet_metrics.py) counts a
// commit in the w-day window when its age is at most w days. A bin k days
// from the end therefore holds ages in (k-1, k], and the newest bin also
// holds ages of zero or less. The sum of the last 7 bins is then exactly
// the board's c7, and the last 30 its c30.

/** Commits per day, oldest first, from commit ages in days. Ages above `days` drop. */
export function binDaily(ages: number[], days = 90): number[] {
  const out = new Array<number>(days).fill(0);
  for (const age of ages) {
    if (!Number.isFinite(age) || age > days) continue;
    const k = Math.max(1, Math.ceil(age));
    out[days - k] += 1;
  }
  return out;
}
