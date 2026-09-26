import type { ReproduceJob } from '../../types/reproduce'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="text-[11px]"><span className="text-zinc-500">{label}: </span><span className="text-zinc-300 break-words">{children}</span></div>
}

/** Evidence per section: what was measured, detected and ranked, and by what. */
export function WhyPanel({ job }: { job: ReproduceJob }) {
  const why = job.why as Record<string, unknown>
  const measured = why.measured as { palette?: { hex: string; share: number }[]; luminance?: number; contrast?: number; saturation?: number; edge_density?: number; sharpness?: number; aspect?: string } | undefined
  const subjects = why.subjects as { source?: string; regions?: { label: string; bbox: number[]; depth_median: number | null }[] } | undefined
  const caption = why.caption as { source?: string; text?: string } | undefined
  const style = why.style as { source?: string; tags?: { term: string; score: number; category: string }[]; negatives?: string[] } | undefined
  const depth = why.depth as { source?: string; near?: number; far?: number; mean?: number } | undefined
  const notes = why.notes as Record<string, string> | undefined
  const vlm = typeof why.vlm === 'string' ? why.vlm : undefined
  if (!measured) return <p className="text-xs text-zinc-600">Analyse the reference to see the evidence behind each block.</p>
  return (
    <div className="space-y-2" data-testid="why-panel">
      <Row label="Measured">
        {measured.aspect} · luminance {measured.luminance?.toFixed(2)} · contrast {measured.contrast?.toFixed(2)} · saturation {measured.saturation?.toFixed(2)} · edges {measured.edge_density?.toFixed(3)} · sharpness {measured.sharpness?.toFixed(4)}
        {measured.palette && (
          <span className="inline-flex gap-1 ml-2 align-middle">
            {measured.palette.map(p => <span key={p.hex} title={`${p.hex} ${(p.share * 100).toFixed(0)}%`} className="inline-block w-3 h-3 rounded-sm border border-zinc-700" style={{ background: p.hex }} />)}
          </span>
        )}
      </Row>
      <Row label={subjects?.source ?? 'Subjects'}>
        {subjects?.regions?.length ? subjects.regions.map((r, i) => <span key={i} className="mr-2">{r.label} [{r.bbox.map(v => v.toFixed(2)).join(', ')}]{r.depth_median !== null ? ` d=${r.depth_median.toFixed(2)}` : ''}</span>) : 'nothing detected'}
      </Row>
      <Row label={caption?.source ?? 'Caption'}>{caption?.text || '—'}</Row>
      <Row label={style?.source ?? 'Style'}>{style?.tags?.length ? style.tags.slice(0, 10).map(t => `${t.term} (${t.category} ${t.score.toFixed(2)})`).join(', ') : '—'}{style?.negatives?.length ? ` · negatives: ${style.negatives.join(', ')}` : ''}</Row>
      <Row label={depth?.source ?? 'Depth'}>{depth?.mean !== undefined ? `mean ${depth.mean.toFixed(2)} (near ${depth.near?.toFixed(2)} · far ${depth.far?.toFixed(2)})` : '—'}</Row>
      {vlm && <Row label="VLM">{vlm}</Row>}
      {notes && Object.keys(notes).length > 0 && <Row label="Notes">{Object.entries(notes).map(([k, v]) => `${k}: ${v}`).join(' · ')}</Row>}
    </div>
  )
}
