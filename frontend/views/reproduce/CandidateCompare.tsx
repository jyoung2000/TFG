import { METRIC_LABEL, type ReproduceCandidate, type ReproduceJob } from '../../types/reproduce'
import { MediaImage } from './MediaImage'
import { MediaBadge, modelName } from './OriginalBadge'

export function MetricBars({ scores }: { scores: ReproduceCandidate['scores'] }) {
  const rows = [['composite', scores.composite] as const, ...Object.entries(scores.components)]
  return (
    <ul className="space-y-1" aria-label="Similarity metrics">
      {rows.map(([name, value]) => (
        <li key={name} className="text-[10px] text-zinc-400">
          <div className="flex justify-between"><span>{METRIC_LABEL[name] ?? name}{scores.weights_used[name] !== undefined && name !== 'composite' ? ` · w ${scores.weights_used[name].toFixed(2)}` : ''}</span><span className={name === 'composite' ? 'text-zinc-100 font-semibold' : ''}>{(value * 100).toFixed(0)}%</span></div>
          <div className="h-1 rounded bg-zinc-800 overflow-hidden" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={METRIC_LABEL[name] ?? name}>
            <div className={`h-full ${name === 'composite' ? 'bg-violet-500' : 'bg-zinc-500'}`} style={{ width: `${Math.max(2, value * 100)}%` }} />
          </div>
        </li>
      ))}
      {scores.missing.length > 0 && <li className="text-[10px] text-zinc-600">not available: {scores.missing.join(', ')}</li>}
    </ul>
  )
}

/** Reference vs best, side by side, with the metric breakdown. */
export function CandidateCompare({ job, candidate }: { job: ReproduceJob; candidate: ReproduceCandidate | null }) {
  const referencePath = job.reference_candidate_id ? (job.candidates.find(c => c.id === job.reference_candidate_id)?.path ?? job.source_path) : job.source_path
  return (
    <div className="grid grid-cols-2 gap-3" data-testid="candidate-compare">
      <figure>
        <div className="relative aspect-video rounded-lg overflow-hidden bg-black ring-2 ring-teal-500/70">
          <MediaBadge kind="original" />
          <MediaImage jobId={job.id} path={referencePath} alt="Original image" className="w-full h-full object-contain" />
        </div>
        <figcaption className="text-[11px] text-teal-300 mt-1">{job.reference_candidate_id ? 'Pinned candidate used as the target' : 'Your image'} · {job.width}×{job.height}</figcaption>
      </figure>
      <figure>
        <div className="relative aspect-video rounded-lg overflow-hidden bg-black ring-2 ring-violet-500/70">
          <MediaBadge kind="reproduction" />
          {candidate ? <MediaImage jobId={job.id} path={candidate.path} alt={`Reproduction ${candidate.id}`} className="w-full h-full object-contain" /> : <div className="h-full flex items-center justify-center text-xs text-zinc-600">No reproduction yet</div>}
        </div>
        <figcaption className="text-[11px] text-violet-300 mt-1">{candidate ? `Best reproduction · ${(candidate.scores.composite * 100).toFixed(1)}% match · ${modelName(candidate.model)} · round ${candidate.round} · seed ${candidate.seed ?? '—'}` : 'Reproduction'}</figcaption>
        {candidate && <div className="mt-2"><MetricBars scores={candidate.scores} /></div>}
      </figure>
    </div>
  )
}
