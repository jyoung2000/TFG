/**
 * Video Reproduce v2, simulated.
 *
 * `start` creates one shot row per analysed shot and renders candidates on
 * the wall clock (one every ~1.5 s), each scored deterministically; candidate
 * clips redirect to the sample clip the dev server already serves, frame
 * thumbnails are labelled SVG placeholders, and Stitch produces a "clip".
 */

import type { ReproduceShot, VideoCandidate, VideoReproduceJob } from '../../../frontend/types/video-reproduce'
import { MockHttpError, RawResponse, type Router } from '../http'
import { placeholderFrame } from '../media'
import type { MockState, Store } from '../state'

const RENDER_MS = 1_500
const origins = new Map<string, number>()
let serial = 0

function scores(composite: number): VideoCandidate['scores'] {
  return {
    composite,
    components: { ssim: composite - 0.05, palette: composite + 0.04, motion: Math.min(0.99, composite + 0.1) },
    weights_used: { ssim: 0.4, palette: 0.4, motion: 0.2 },
    missing: ['clip', 'dino', 'layout'],
  }
}

function find(state: MockState, id: string): VideoReproduceJob {
  const job = state.videoReproduce[id]
  if (!job) return { version: 1, analysis_id: id, project_id: '', title: '', kind: 'preview', target: 'ltx-2-3-fast', model: 'fast', resolution: '540p', fps: 24, candidates_per_shot: 2, rounds: 1, seed: null, status: 'idle', progress: 0, message: '', error: '', shots: [], stitched_path: '', stitched_at: null, job_id: '', peak_vram_mb: null, created_at: Date.now(), updated_at: Date.now() }
  return job
}

function best(shot: ReproduceShot): VideoCandidate | null {
  return shot.candidates.filter(c => c.status === 'complete').reduce<VideoCandidate | null>((b, c) => (b === null || c.scores.composite > b.scores.composite ? c : b), null)
}

/** Advance every running job to the present. */
export function tickVideoReproduce(state: MockState): void {
  const now = Date.now()
  for (const job of Object.values(state.videoReproduce)) {
    if (job.status !== 'running') continue
    const origin = origins.get(job.analysis_id) ?? job.updated_at
    const pending = job.shots.flatMap(shot => shot.candidates.filter(c => c.status !== 'complete').map(c => ({ shot, c })))
    const total = job.shots.reduce((n, s) => n + s.candidates.length, 0)
    const finished = Math.min(total, Math.floor((now - origin) / RENDER_MS))
    let done = job.shots.reduce((n, s) => n + s.candidates.filter(c => c.status === 'complete').length, 0)
    for (const { shot, c } of pending) {
      if (done >= finished) break
      c.status = 'complete'
      c.path = `ui-mock/outputs/${job.analysis_id}/${c.id}.mp4`
      c.frames = ['start', 'middle', 'end'].map(role => `${c.id}-${role}.jpg`)
      c.scores = scores(Math.min(0.97, 0.55 + shot.index * 0.03 + c.round * 0.08 + (shot.candidates.indexOf(c) % 2) * 0.05))
      c.motion_match = c.scores.components.motion
      done += 1
      const top = best(shot)
      shot.best_candidate_id = top?.id ?? ''
      if (!shot.picked_candidate_id || !shot.candidates.some(x => x.id === shot.picked_candidate_id)) shot.picked_candidate_id = shot.best_candidate_id
    }
    job.progress = total ? done / total : 1
    if (done >= total) {
      job.status = 'complete'
      job.progress = 1
      job.stitched_path = `stitched-${now}.mp4`
      job.stitched_at = now
      job.message = `${done} candidates across ${job.shots.length} shots · stitched`
    } else {
      const next = pending[Math.max(0, done - (total - pending.length))]
      job.message = next ? `Shot ${next.shot.index + 1}: candidate ${next.shot.candidates.indexOf(next.c) + 1} of ${next.shot.candidates.length}` : 'rendering'
    }
    job.updated_at = now
  }
}

export function registerVideoReproduceRoutes(router: Router, store: Store, clipUrl: string): void {
  router.get('/api/video-reproduce/:id', req => store.mutate(state => { tickVideoReproduce(state); return find(state, req.params.id) }))

  router.post('/api/video-reproduce/:id/start', req => store.mutate(state => {
    tickVideoReproduce(state)
    const analysis = state.analyses[req.params.id]
    if (!analysis) throw new MockHttpError(404, 'Video analysis not found')
    if (analysis.shots.length === 0) throw new MockHttpError(400, 'No shots available. Detect and analyze shots first.')
    if (!analysis.shots.some(s => s.prompts.video.trim() || Object.keys(s.spec.provenance).length)) throw new MockHttpError(400, 'No valid prompts available for recreation. Analyze shots first.')
    const existing = state.videoReproduce[analysis.id]
    if (existing?.status === 'running') throw new MockHttpError(409, 'This video is already being reproduced')
    const ids = Array.isArray(req.body.shot_ids) ? (req.body.shot_ids as string[]) : []
    const selected = ids.length ? analysis.shots.filter(s => ids.includes(s.id)) : analysis.shots
    if (selected.length === 0) throw new MockHttpError(400, 'No matching shots found for the provided shot IDs')
    const candidates = Math.max(1, Math.min(6, Number(req.body.candidates ?? 2)))
    const rounds = Math.max(1, Math.min(3, Number(req.body.rounds ?? 1)))
    const seed = typeof req.body.seed === 'number' ? req.body.seed : null
    const now = Date.now()
    const job: VideoReproduceJob = {
      version: 1, analysis_id: analysis.id, project_id: analysis.reconstructed_project_id || 'film-mock-reproduce', title: analysis.title,
      kind: 'preview', target: 'ltx-2-3-fast', model: 'fast', resolution: '540p', fps: 24, candidates_per_shot: candidates, rounds, seed,
      status: 'running', progress: 0, message: 'Preparing shots', error: '', shots: [], stitched_path: '', stitched_at: null,
      job_id: `job_vr_${++serial}`, peak_vram_mb: 9800, created_at: now, updated_at: now,
    }
    for (const shot of selected) {
      const row: ReproduceShot = {
        shot_id: shot.id, index: shot.index, film_scene_id: 'scene-mock', film_shot_id: `film-${shot.id}`, start: shot.start, end: shot.end,
        duration_seconds: [6, 8, 10].reduce((a, b) => (Math.abs(b - shot.duration) < Math.abs(a - shot.duration) ? b : a)),
        start_frame: shot.frames[0]?.path ?? '', prompt: shot.prompts.video || `Shot ${shot.index + 1}`, negative_prompt: shot.prompts.negative,
        prompt_source: shot.prompts.edited ? 'user' : 'spec', candidates: [], best_candidate_id: '', picked_candidate_id: '',
      }
      for (let r = 1; r <= rounds; r++) for (let n = 0; n < candidates; n++) {
        row.candidates.push({ id: `vc-${shot.index}-${r}-${n + 1}`, version_number: r * 10 + n, path: '', frames: [], prompt: row.prompt, negative_prompt: row.negative_prompt,
          seed: seed === null ? null : seed + (r - 1) * 100 + n, round: r, model: 'fast', target: 'ltx-2-3-fast', duration_seconds: row.duration_seconds,
          status: 'queued', error: '', scores: { composite: 0, components: {}, weights_used: {}, missing: [] }, motion_match: null, job_id: `job_vg_${shot.index}_${r}_${n}`, created_at: now })
      }
      job.shots.push(row)
    }
    state.videoReproduce[analysis.id] = job
    origins.set(analysis.id, now)
    return { status: job.status, video_paths: null, shots_generated: 0, analysis_id: analysis.id }
  }))

  router.post('/api/video-reproduce/:id/cancel', req => store.mutate(state => {
    tickVideoReproduce(state)
    const job = find(state, req.params.id)
    if (job.status === 'running') {
      job.status = 'cancelled'
      job.message = 'Cancelled'
      for (const shot of job.shots) for (const c of shot.candidates) if (c.status !== 'complete') c.status = 'cancelled'
      job.updated_at = Date.now()
    }
    return job
  }))

  router.post('/api/video-reproduce/:id/shots/:shotId/pick/:candidateId', req => store.mutate(state => {
    const job = find(state, req.params.id)
    const shot = job.shots.find(s => s.shot_id === req.params.shotId)
    if (!shot) throw new MockHttpError(404, 'No such shot in this reproduce job')
    const candidate = shot.candidates.find(c => c.id === req.params.candidateId)
    if (!candidate || candidate.status !== 'complete') throw new MockHttpError(404, 'That candidate was not rendered')
    shot.picked_candidate_id = candidate.id
    job.updated_at = Date.now()
    return job
  }))

  router.post('/api/video-reproduce/:id/shots/:shotId/redo', req => store.mutate(state => {
    tickVideoReproduce(state)
    const job = find(state, req.params.id)
    if (job.status === 'running') throw new MockHttpError(409, 'This video is already being reproduced')
    const shot = job.shots.find(s => s.shot_id === req.params.shotId)
    if (!shot) throw new MockHttpError(404, 'No such shot in this reproduce job')
    const round = Math.max(0, ...shot.candidates.map(c => c.round)) + 1
    shot.candidates.push({ id: `vc-${shot.index}-${round}-1`, version_number: round * 10, path: '', frames: [], prompt: shot.prompt, negative_prompt: shot.negative_prompt,
      seed: job.seed === null ? null : job.seed + (round - 1) * 100, round, model: 'fast', target: 'ltx-2-3-fast', duration_seconds: shot.duration_seconds,
      status: 'queued', error: '', scores: { composite: 0, components: {}, weights_used: {}, missing: [] }, motion_match: null, job_id: `job_vg_redo_${round}`, created_at: Date.now() })
    job.status = 'running'
    job.message = `Shot ${shot.index + 1}: one more candidate`
    job.updated_at = Date.now()
    // Only the new candidate is pending; the origin is set so it lands after one tick.
    origins.set(job.analysis_id, Date.now() - RENDER_MS * (job.shots.reduce((n, s) => n + s.candidates.filter(c => c.status === 'complete').length, 0)))
    return job
  }))

  router.post('/api/video-reproduce/:id/stitch', req => store.mutate(state => {
    tickVideoReproduce(state)
    const job = find(state, req.params.id)
    if (job.status === 'running') throw new MockHttpError(409, 'Wait for the render to finish before stitching')
    if (!job.shots.some(s => s.candidates.some(c => c.status === 'complete'))) throw new MockHttpError(400, 'No rendered candidate to stitch')
    job.stitched_path = `stitched-${Date.now()}.mp4`
    job.stitched_at = Date.now()
    job.updated_at = Date.now()
    return job
  }))

  router.get('/api/video-reproduce/:id/media', req => {
    const job = find(store.data, req.params.id)
    const path = req.query.get('path') ?? ''
    const clips = new Set(job.shots.flatMap(s => s.candidates.map(c => c.path)).filter(Boolean))
    if (path === job.stitched_path || clips.has(path)) {
      if (!clipUrl) throw new MockHttpError(404, 'No sample clip configured')
      return new RawResponse(302, { location: clipUrl }, null)
    }
    const frames = new Set(job.shots.flatMap(s => s.candidates.flatMap(c => c.frames)))
    if (!frames.has(path)) throw new MockHttpError(400, 'File is not part of this reproduce job')
    return placeholderFrame(`Candidate frame (UI MOCK)`, path, `${job.analysis_id}/${path}`)
  })
}
