/**
 * Inline SVG loss curve. No charting library: a training run reports a few
 * hundred points at most, and this stays crisp at any size.
 */
export function LossSparkline({ values, width = 240, height = 48, label = 'Loss' }: { values: number[]; width?: number; height?: number; label?: string }) {
  if (values.length < 2) {
    return <div className="text-[11px] text-zinc-600" data-testid="loss-sparkline" aria-label={`${label}: waiting for data`}>{label}: waiting for the first steps…</div>
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pad = 2
  const points = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2)
    const y = pad + (1 - (v - min) / span) * (height - pad * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  const last = values[values.length - 1]
  const first = values[0]
  return (
    <figure className="m-0" data-testid="loss-sparkline">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} ${first.toFixed(3)} to ${last.toFixed(3)} over ${values.length} points`} className="block">
        <polyline points={points.join(' ')} fill="none" stroke="#a78bfa" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={points[points.length - 1].split(',')[0]} cy={points[points.length - 1].split(',')[1]} r="2" fill="#c4b5fd" />
      </svg>
      <figcaption className="text-[10px] text-zinc-500 flex justify-between"><span>{label} · {values.length} pts</span><span>min {min.toFixed(3)} · last {last.toFixed(3)}</span></figcaption>
    </figure>
  )
}
