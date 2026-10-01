import { useCallback, useEffect, useState } from 'react'
import { Clapperboard, Copy, Loader2, Play, RefreshCw, Scissors, Square, Star, X } from 'lucide-react'
import { analysisFrameUrl } from '../../lib/video-analysis-api'
import { videoReproduceApi, videoReproduceMediaUrl } from '../../lib/video-reproduce-api'
import { METRIC_LABEL } from '../../types/reproduce'
import type { VideoAnalysis } from '../../types/video-analysis'
import { chosenCandidate, type ReproduceShot, type VideoCandidate, type VideoReproduceJob } from '../../types/video-reproduce'
import { MediaBadge, modelName, strategyName } from './OriginalBadge'

/**
 * Video Reproduce v2: one strip per analysed shot — the original next to the
 * chosen reproduction, each labelled, with the model / prompt / settings that
 * made the take beside it — plus pick / redo, Stitch, and the storyboard the
 * run builds as it goes. Every clip plays through the authenticated media route.
 */
export function VideoReproducePanel({ analysis, job, onJob, onClose, onOpenStoryboard }: { analysis: VideoAnalysis; job: VideoReproduceJob; onJob: (job: VideoReproduceJob) => void; onClose: () => void; onOpenStoryboard?: (projectId: string) => void }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const running = job.status === 'running'

  // Poll while the queue renders.
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(async () => {
      try { onJob(await videoReproduceApi.get(analysis.id)) } catch { /* transient */ }
    }, 1200)
    return () => window.clearInterval(timer)
  }, [running, analysis.id, onJob])

  const run = useCallback(async (label: string, work: () => Promise<VideoReproduceJob>) => {
    setBusy(label)
    setError('')
    try { onJob(await work()) } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy('') }
  }, [onJob])

  const rendered = job.shots.reduce((n, s) => n + s.candidates.filter(c => c.status === 'complete').length, 0)

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 space-y-3" data-testid="video-reproduce" aria-label="Video reproduce">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-white">Video reproduce</h2>
        <span className={`text-xs ${job.status === 'failed' ? 'text-red-300' : running ? 'text-violet-300' : 'text-zinc-400'}`} data-testid="video-reproduce-status">
          {job.status}{running ? ` ${Math.round(job.progress * 100)}% · ${job.message}` : job.message ? ` · ${job.message}` : ''}
        </span>
        <span className="text-[11px] text-zinc-500">{job.model} · {job.resolution} · {rendered} rendered{job.peak_vram_mb ? ` · peak ${(job.peak_vram_mb / 1024).toFixed(1)} GB` : ''}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {running ? (
            <button onClick={() => void run('Cancelling', () => videoReproduceApi.cancel(analysis.id))} className="btn-chip text-red-300"><Square className="h-3.5 w-3.5" /> Cancel</button>
          ) : (
            <button onClick={() => void run('Stitching', () => videoReproduceApi.stitch(analysis.id))} disabled={!!busy || rendered === 0} className="btn-chip">{busy === 'Stitching' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />} Stitch picks</button>
          )}
          {onOpenStoryboard && job.project_id && <button onClick={() => onOpenStoryboard(job.project_id)} className="btn-chip" title="The storyboard this run builds: one shot per original shot, its 3D composition, cast and the chosen take" data-testid="video-reproduce-open-storyboard"><Clapperboard className="h-3.5 w-3.5" /> Open 3D storyboard</button>}
          <button onClick={onClose} aria-label="Close video reproduce" className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-white"><X className="h-4 w-4" /></button>
        </span>
      </div>
      {error && <p className="text-xs text-red-300" role="alert">{error}</p>}
      {job.error && !error && <p className="text-xs text-red-300">{job.error}</p>}

      <div className="space-y-2" data-testid="video-reproduce-strip">
        {job.shots.map(shot => (
          <ShotRow key={shot.shot_id} analysis={analysis} job={job} shot={shot} busy={!!busy || running}
            onPick={c => void run('Picking', () => videoReproduceApi.pick(analysis.id, shot.shot_id, c.id))}
            onRedo={() => void run('Redo', () => videoReproduceApi.redo(analysis.id, shot.shot_id))} />
        ))}
      </div>

      {job.stitched_path && (
        <div className="space-y-1" data-testid="video-reproduce-stitched">
          <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Whole video · original vs reproduction</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <figure className="space-y-1">
              <div className="relative aspect-video rounded overflow-hidden bg-black ring-2 ring-teal-500/70"><MediaBadge kind="original" /><MediaVideo analysisId={analysis.id} path="source" label="Original video" /></div>
              <figcaption className="text-[10px] text-teal-300">{analysis.source.file_name}</figcaption>
            </figure>
            <figure className="space-y-1">
              <div className="relative aspect-video rounded overflow-hidden bg-black ring-2 ring-violet-500/70"><MediaBadge kind="reproduction" /><MediaVideo analysisId={analysis.id} path={job.stitched_path} label="Stitched reproduction" /></div>
              <figcaption className="text-[10px] text-violet-300">The chosen take of every shot, stitched</figcaption>
            </figure>
          </div>
        </div>
      )}
    </section>
  )
}

function ShotRow({ analysis, job, shot, busy, onPick, onRedo }: { analysis: VideoAnalysis; job: VideoReproduceJob; shot: ReproduceShot; busy: boolean; onPick: (c: VideoCandidate) => void; onRedo: () => void }) {
  const chosen = chosenCandidate(shot)
  const source = analysis.shots.find(s => s.id === shot.shot_id)
  const frame = source?.frames[0]?.path || ''
  const [refUrl, setRefUrl] = useState('')
  useEffect(() => {
    let active = true
    if (!frame || shot.reference_clip) return
    analysisFrameUrl(analysis.id, frame).then(u => { if (active) setRefUrl(u) }).catch(() => undefined)
    return () => { active = false }
  }, [analysis.id, frame, shot.reference_clip])
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-2 space-y-2" data-testid="video-reproduce-shot">
      <p className="text-[11px] text-zinc-300 font-semibold">Shot {shot.index + 1} <span className="font-normal text-zinc-500">· original {shot.start.toFixed(2)}–{shot.end.toFixed(2)}s → rendered {shot.duration_seconds}s</span></p>
      <div className="flex gap-3 flex-wrap">
        <figure className="w-64 shrink-0 space-y-1" data-testid="video-reproduce-original">
          <div className="relative aspect-video rounded overflow-hidden bg-black ring-2 ring-teal-500/70">
            <MediaBadge kind="original" />
            {shot.reference_clip
              ? <MediaVideo analysisId={analysis.id} path={shot.reference_clip} label={`Shot ${shot.index + 1} original`} />
              : refUrl && <img src={refUrl} alt={`Shot ${shot.index + 1} original frame`} className="w-full h-full object-cover" />}
          </div>
          <figcaption className="text-[10px] text-teal-300">Your video · {shot.reference_clip ? 'this shot' : 'a frame of this shot'}</figcaption>
        </figure>
        <figure className="w-64 shrink-0 space-y-1" data-testid="video-reproduce-result">
          <div className="relative aspect-video rounded overflow-hidden bg-black ring-2 ring-violet-500/70">
            <MediaBadge kind="reproduction" />
            {chosen?.status === 'complete' && chosen.path ? <MediaVideo analysisId={analysis.id} path={chosen.path} label={`Shot ${shot.index + 1} reproduction`} /> : <div className="w-full h-full flex items-center justify-center text-[10px] text-zinc-600">{shot.candidates.length ? 'rendering…' : 'no candidate yet'}</div>}
          </div>
          <figcaption className="text-[10px] text-violet-300">{chosen ? `${chosen.id === shot.picked_candidate_id ? 'Chosen take' : 'Latest take'} · ${chosen.status === 'complete' ? `${(chosen.scores.composite * 100).toFixed(1)}% match` : chosen.status}` : 'Reproduction'}</figcaption>
          {chosen && <Scores candidate={chosen} />}
        </figure>
        <div className="flex-1 min-w-[16rem]">{chosen ? <MadeWith candidate={chosen} /> : <p className="text-[10px] text-zinc-600">The model, prompt and settings of the take appear here.</p>}</div>
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-1 text-[10px] text-zinc-500">
          <span>{shot.candidates.length} candidate{shot.candidates.length === 1 ? '' : 's'}</span>
          {shot.note && <span className={shot.reached ? 'text-emerald-300' : 'text-zinc-400'} title={shot.note}>· {shot.note}</span>}
          <button onClick={onRedo} disabled={busy || job.status === 'running'} className="btn-chip ml-auto" aria-label={`Redo shot ${shot.index + 1}`}><RefreshCw className="h-3 w-3" /> Redo</button>
        </div>
        <ul className="flex flex-wrap gap-1.5">
          {shot.candidates.map(candidate => (
            <li key={candidate.id} className={`rounded border p-1 w-28 ${candidate.id === shot.picked_candidate_id ? 'border-amber-400/70' : candidate.id === shot.best_candidate_id ? 'border-violet-600' : 'border-zinc-800'}`} data-testid="video-reproduce-candidate">
              <Thumb analysisId={analysis.id} candidate={candidate} />
              <div className="flex items-center gap-1 text-[10px] text-zinc-400 mt-0.5">
                <span className="font-semibold text-zinc-200">{candidate.status === 'complete' ? `${(candidate.scores.composite * 100).toFixed(0)}%` : candidate.status}</span>
                <span title={`${modelName(candidate.model)}${candidate.strategy ? ` · ${strategyName(candidate.strategy)}` : ''}${candidate.control_strength != null ? ` @ ${candidate.control_strength.toFixed(2)}` : ''}`}>r{candidate.round}{candidate.seed !== null ? ` · ${candidate.seed}` : ''}</span>
                {candidate.status === 'complete' && (
                  <button onClick={() => onPick(candidate)} disabled={busy} aria-label={`Pick ${candidate.id}`} aria-pressed={candidate.id === shot.picked_candidate_id} className={`ml-auto p-0.5 rounded ${candidate.id === shot.picked_candidate_id ? 'text-amber-300' : 'hover:text-white'}`}><Star className="h-3 w-3" /></button>
                )}
              </div>
              {candidate.error && <p className="text-[9px] text-red-300 line-clamp-2" title={candidate.error}>{candidate.error}</p>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/** What made a take: the model that rendered it, how it was guided, the seed and the prompts. */
function MadeWith({ candidate }: { candidate: VideoCandidate }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(candidate.prompt); setCopied(true) } catch { /* clipboard unavailable */ }
  }
  return (
    <dl className="rounded border border-zinc-800 bg-zinc-900/60 p-2 text-[10px] space-y-1" data-testid="video-reproduce-made-with" aria-label="How this take was made">
      <div className="flex gap-2"><dt className="w-14 shrink-0 text-zinc-500">Model</dt><dd className="text-zinc-100 font-semibold" data-testid="made-with-model">{modelName(candidate.model)}</dd></div>
      {candidate.strategy && <div className="flex gap-2"><dt className="w-14 shrink-0 text-zinc-500">Guided</dt><dd className="text-zinc-300">{strategyName(candidate.strategy)}{candidate.control_strength != null ? ` · strength ${candidate.control_strength.toFixed(2)}` : ''}</dd></div>}
      <div className="flex gap-2"><dt className="w-14 shrink-0 text-zinc-500">Take</dt><dd className="text-zinc-300">round {candidate.round} · seed {candidate.seed ?? 'random'} · {candidate.duration_seconds}s</dd></div>
      <div className="flex gap-2"><dt className="w-14 shrink-0 text-zinc-500">Prompt</dt><dd className="text-zinc-300 whitespace-pre-wrap break-words max-h-28 overflow-y-auto" data-testid="made-with-prompt">{candidate.prompt || '—'}</dd></div>
      {candidate.negative_prompt && <div className="flex gap-2"><dt className="w-14 shrink-0 text-zinc-500">Negative</dt><dd className="text-zinc-400 break-words">{candidate.negative_prompt}</dd></div>}
      <button onClick={() => void copy()} className="btn-chip"><Copy className="h-3 w-3" /> {copied ? 'Copied' : 'Copy prompt'}</button>
    </dl>
  )
}

function Scores({ candidate }: { candidate: VideoCandidate }) {
  const rows = Object.entries(candidate.scores.components)
  if (rows.length === 0) return <p className="text-[10px] text-zinc-600">not scored</p>
  return (
    <ul className="space-y-0.5" aria-label="Candidate scores">
      {rows.map(([name, value]) => (
        <li key={name} className="text-[9px] text-zinc-500">
          <span className="inline-block w-24 truncate align-middle">{METRIC_LABEL[name] ?? (name === 'motion' ? 'Motion match' : name)}</span>
          <span className="inline-block w-20 h-1 rounded bg-zinc-800 align-middle overflow-hidden" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={name}><span className="block h-full bg-violet-500" style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} /></span>
          <span className="ml-1 text-zinc-400">{(value * 100).toFixed(0)}%</span>
        </li>
      ))}
    </ul>
  )
}

function Thumb({ analysisId, candidate }: { analysisId: string; candidate: VideoCandidate }) {
  const frame = candidate.frames[1] ?? candidate.frames[0] ?? ''
  const [url, setUrl] = useState('')
  useEffect(() => {
    let active = true
    if (!frame) return
    videoReproduceMediaUrl(analysisId, frame).then(u => { if (active) setUrl(u) }).catch(() => undefined)
    return () => { active = false }
  }, [analysisId, frame])
  return <div className="aspect-video rounded bg-black overflow-hidden">{url ? <img src={url} alt={`Candidate ${candidate.id} frame`} className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center"><Play className="h-3 w-3 text-zinc-700" /></div>}</div>
}

/** A rendered clip through the authenticated media route (never `file://`). */
export function MediaVideo({ analysisId, path, label }: { analysisId: string; path: string; label: string }) {
  const [url, setUrl] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    setUrl(''); setFailed(false)
    videoReproduceMediaUrl(analysisId, path).then(u => { if (active) setUrl(u) }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [analysisId, path])
  if (!url && !failed) return <div className="w-full h-full animate-pulse bg-zinc-900" aria-label={`Loading ${label}`} />
  if (!url) return <p className="text-[10px] text-red-300 p-2">{label} could not be resolved</p>
  // The element stays mounted on a playback error: the file may be fine and
  // only the codec missing in this browser, and the caption says which.
  return (
    <div className="relative w-full h-full">
      <video src={url} controls preload="metadata" aria-label={label} className="w-full h-full object-contain" onError={() => setFailed(true)} />
      {failed && <p className="absolute inset-x-0 bottom-0 text-[10px] text-amber-300 bg-black/70 px-2 py-1">{label}: playback unavailable here (file still served)</p>}
    </div>
  )
}
