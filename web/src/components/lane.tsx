// A 30-day activity lane: a tiny strip of the strata for one subnet.
// Mark height and alpha follow log1p(commits that day), as in the field.
export function Lane({ daily, days = 30 }: { daily: number[] | null; days?: number }) {
  if (!daily) return <span className="text-ink-3">-</span>;
  const d = daily.slice(-days);
  const total = d.reduce((a, b) => a + b, 0);
  const W = days * 6;
  const H = 14;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="ml-auto block h-3.5 w-[90px] md:w-[150px]"
      role="img"
      aria-label={`${total} commits in the last ${days} days, at most ${Math.max(...d)} in one day`}
    >
      {d.map((v, i) => {
        const a = v ? Math.min(1, Math.log1p(v) / 2.2) : 0;
        const h = a ? Math.max(2, H * a) : 1;
        return a ? (
          <rect key={i} x={i * 6} y={(H - h) / 2} width={4.5} height={h} className="fill-accent-2" fillOpacity={0.3 + a * 0.7} />
        ) : (
          <rect key={i} x={i * 6} y={(H - h) / 2} width={4.5} height={h} className="fill-rule" />
        );
      })}
    </svg>
  );
}
