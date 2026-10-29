// One series, one question. A bar per point, a faint scale of three lines,
// dates on the first and last bar. No legend: the title names the series.
export function BarChart({
  points,
  unit,
  digits = 1,
  label,
}: {
  points: { x: string; y: number }[];
  unit: string;
  digits?: number;
  label: string;
}) {
  const ys = points.map((p) => p.y);
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const pad = (hi - lo) * 0.15 || 1;
  const min = lo - pad;
  const max = hi + pad;
  const W = 600;
  const H = 180;
  const bw = W / points.length;
  const y = (v: number) => H - ((v - min) / (max - min)) * H;
  const ticks = [min + (max - min) * 0.2, (min + max) / 2, max - (max - min) * 0.2];
  const fmt = (v: number) => `${v.toFixed(digits)}${unit}`;

  return (
    <figure>
      <svg viewBox={`0 0 ${W + 56} ${H + 24}`} className="w-full" role="img" aria-label={`${label}: from ${fmt(ys[0])} on ${points[0].x} to ${fmt(ys[ys.length - 1])} on ${points[points.length - 1].x}, low ${fmt(lo)}, high ${fmt(hi)}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={0} x2={W} y1={y(t)} y2={y(t)} stroke="currentColor" strokeOpacity={0.12} />
            <text x={W + 8} y={y(t) + 4} className="fill-muted text-[12px]">
              {fmt(t)}
            </text>
          </g>
        ))}
        {points.map((p, i) => (
          <rect key={p.x} x={i * bw + 1} y={y(p.y)} width={Math.max(1, bw - 2)} height={H - y(p.y)} className="fill-ink" />
        ))}
        <text x={0} y={H + 18} className="fill-muted text-[12px]">{points[0].x}</text>
        <text x={W} y={H + 18} textAnchor="end" className="fill-muted text-[12px]">{points[points.length - 1].x}</text>
      </svg>
    </figure>
  );
}
