import { useCallback, useEffect, useState } from 'react'
import { Loader2, Play, RefreshCw, Scissors, Square, Star, X } from 'lucide-react'
import { analysisFrameUrl } from '../../lib/video-analysis-api'
import { videoReproduceApi, videoReproduceMediaUrl } from '../../lib/video-reproduce-api'
import { METRIC_LABEL } from '../../types/reproduce'
import type { VideoAnalysis } from '../../types/video-analysis'
import { chosenCandidate, type ReproduceShot, type VideoCandidate, type VideoReproduceJob } from '../../types/video-reproduce'

/**
 * Video Reproduce v2: one strip per analysed shot — the reference frame next
 * to the chosen candidate — with per-shot scores, pick / redo, and Stitch.
 * Every clip plays through the authenticated media route.
 */
export function VideoReproducePanel({ analysis, job, onJob, onClose, onBuild3D }: { analysis: VideoAnalysis; job: VideoReproduceJob; onJob: (job: VideoReproduceJob) => void; onClose: () => void; onBuild3D?: () => void }) {
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
          {onBuild3D && !running && <button onClick={onBuild3D} className="btn-chip" title="Storyboard whose shots open the composer pre-seeded from this analysis">Build 3D storyboard</button>}
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
          <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Stitched result</h3>
          <div className="max-w-xl aspect-video rounded overflow-hidden bg-black"><MediaVideo analysisId={analysis.id} path={job.stitched_path} label="Stitched result" /></div>
        </div>
      )}
    </section>
  )
}

function ShotRow({ analysis, job, shot, busy, onPick, onRedo }: { analysis: VideoAnalysis; job: VideoReproduceJob; shot: ReproduceShot; busy: boolean; onPick: (c: VideoCandidate) => void; onRedo: () => void }) {
  const chosen = chosenCandidate(shot)
  const source = analysis.shots.find(s => s.id === shot.shot_id)
  const reference = shot.start_frame || source?.frames[0]?.path || ''
  const [refUrl, setRefUrl] = useState('')
  useEffect(() => {
    let active = true
    if (!reference) return
    analysisFrameUrl(analysis.id, reference).then(u => { if (active) setRefUrl(u) }).catch(() => undefined)
    return () => { active = false }
  }, [analysis.id, reference])
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-2 flex gap-3" data-testid="video-reproduce-shot">
      <div className="w-40 shrink-0 space-y-1">
        <div className="aspect-video rounded overflow-hidden bg-black">{refUrl && <img src={refUrl} alt={`Shot ${shot.index + 1} reference frame`} className="w-full h-full object-cover" />}</div>
        <p className="text-[10px] text-zinc-400">Shot {shot.index + 1} · {shot.start.toFixed(1)}–{shot.end.toFixed(1)}s → {shot.duration_seconds}s</p>
        <p className="text-[10px] text-zinc-600 line-clamp-2" title={shot.prompt}>{shot.prompt_source} prompt</p>
      </div>
      <div className="w-56 shrink-0 space-y-1">
        <div className="aspect-video rounded overflow-hidden bg-black">
          {chosen?.status === 'complete' && chosen.path ? <MediaVideo analysisId={analysis.id} path={chosen.path} label={`Shot ${shot.index + 1} candidate`} /> : <div className="w-full h-full flex items-center justify-center text-[10px] text-zinc-600">{shot.candidates.length ? 'rendering…' : 'no candidate yet'}</div>}
        </div>
        {chosen && <Scores candidate={chosen} />}
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-1 text-[10px] text-zinc-500">
          <span>{shot.candidates.length} candidate{shot.candidates.length === 1 ? '' : 's'}</span>
          <button onClick={onRedo} disabled={busy || job.status === 'running'} className="btn-chip ml-auto" aria-label={`Redo shot ${shot.index + 1}`}><RefreshCw className="h-3 w-3" /> Redo</button>
        </div>
        <ul className="flex flex-wrap gap-1.5">
          {shot.candidates.map(candidate => (
            <li key={candidate.id} className={`rounded border p-1 w-28 ${candidate.id === shot.picked_candidate_id ? 'border-amber-400/70' : candidate.id === shot.best_candidate_id ? 'border-violet-600' : 'border-zinc-800'}`} data-testid="video-reproduce-candidate">
              <Thumb analysisId={analysis.id} candidate={candidate} />
              <div className="flex items-center gap-1 text-[10px] text-zinc-400 mt-0.5">
                <span className="font-semibold text-zinc-200">{candidate.status === 'complete' ? `${(candidate.scores.composite * 100).toFixed(0)}%` : candidate.status}</span>
                <span>r{candidate.round}{candidate.seed !== null ? ` · ${candidate.seed}` : ''}</span>
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
