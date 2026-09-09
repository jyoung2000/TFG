/**
 * The film production queue, simulated.
 *
 * One job runs at a time, exactly as the real backend allows, and progress is
 * derived from elapsed wall-clock time rather than a timer — so the queue
 * advances whenever the UI polls it and nothing keeps running after the dev
 * server is idle.
 */

import type { FilmProject, FilmShot, VersionKind, ShotVersion } from '../../../frontend/types/film'
import { MockHttpError, type Router } from '../http'
import { DEMO_OUTPUT } from '../seed'
import { jobProgress, queueSnapshot, type MockJob, type MockState, type Store } from '../state'

/** How long a simulated render takes. Short enough to watch, long enough to see progress. */
const PREVIEW_MS = 9000
const FINAL_MS = 16000

function locate(project: FilmProject, shotId: string): { sceneId: string; shot: FilmShot } | null {
  for (const scene of project.scenes) {
    const shot = scene.shots.find(s => s.id === shotId)
    if (shot) return { sceneId: scene.id, shot }
  }
  return null
}

function versionOf(shot: FilmShot, number: number): ShotVersion | undefined {
  return shot.versions.find(v => v.number === number)
}

function newVersion(project: FilmProject, shot: FilmShot, kind: VersionKind): ShotVersion {
  const number = shot.versions.length + 1
  const preview = kind === 'preview'
  const version: ShotVersion = {
    number,
    kind,
    status: 'queued',
    prompt: shot.visual_prompt || `${shot.title}. ${shot.action}`.trim(),
    negative_prompt: shot.negative_prompt || project.settings.default_negative_prompt,
    model: shot.generation.model || (preview ? 'fast' : project.settings.default_model),
    resolution:
      shot.generation.resolution ||
      (preview ? project.settings.preview_resolution : project.settings.default_resolution),
    fps: shot.generation.fps,
    duration_seconds: preview
      ? Math.min(shot.duration_seconds, project.settings.preview_max_seconds)
      : shot.duration_seconds,
    seed: shot.generation.seed,
    capture_path: shot.capture_path,
    output_path: '',
    error: '',
    wardrobe_snapshot: {},
    shot_snapshot: {},
    generation_seconds: null,
    gpu_name: 'NVIDIA GeForce RTX 4070',
    peak_vram_gb: null,
    execution_mode: 'wangp',
    created_at: Date.now(),
  }
  shot.versions.push(version)
  return version
}

function enqueue(state: MockState, project: FilmProject, shot: FilmShot, sceneId: string, kind: VersionKind): MockJob {
  const version = newVersion(project, shot, kind)
  shot.status = 'queued'
  const job: MockJob = {
    project_id: project.id,
    scene_id: sceneId,
    shot_id: shot.id,
    shot_title: shot.title,
    kind,
    version_number: version.number,
    status: 'queued',
    started_at: null,
    duration_ms: kind === 'preview' ? PREVIEW_MS : FINAL_MS,
  }
  state.queue.pending.push(job)
  return job
}

function finish(state: MockState, job: MockJob, outcome: 'complete' | 'cancelled'): void {
  const project = state.projects[job.project_id]
  const found = project ? locate(project, job.shot_id) : null
  if (!project || !found) return
  const version = versionOf(found.shot, job.version_number)
  if (version) {
    version.status = outcome
    if (outcome === 'complete') {
      version.output_path = DEMO_OUTPUT
      version.generation_seconds = Math.round((job.duration_ms / 1000) * 10) / 10
      version.peak_vram_gb = job.kind === 'preview' ? 7.1 : 10.8
      found.shot.current_version = version.number
    }
  }
  found.shot.status = outcome === 'complete' ? 'review' : found.shot.capture_path ? 'ready' : 'draft'
  found.shot.updated_at = Date.now()
  project.updated_at = Date.now()
}

/**
 * Advance the simulated queue to the present. Called before every request so
 * any endpoint sees a consistent view.
 */
export function tickQueue(state: MockState): void {
  const active = state.queue.active
  if (active && active.started_at != null && Date.now() - active.started_at >= active.duration_ms) {
    finish(state, active, 'complete')
    state.queue.active = null
  }
  if (!state.queue.active && !state.queue.paused) {
    const next = state.queue.pending.shift()
    if (next) {
      next.started_at = Date.now()
      next.status = 'generating'
      state.queue.active = next
      const project = state.projects[next.project_id]
      const found = project ? locate(project, next.shot_id) : null
      if (found) {
        found.shot.status = 'generating'
        const version = versionOf(found.shot, next.version_number)
        if (version) version.status = 'generating'
      }
    }
  }
}

export function registerQueueRoutes(router: Router, store: Store): void {
  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/generate', req =>
    store.mutate(state => {
      const project = store.ensureProject(req.params.projectId)
      const found = locate(project, req.params.shotId)
      if (!found) throw new MockHttpError(404, `Shot not found: ${req.params.shotId}`)
      const kind: VersionKind = req.body.kind === 'final' ? 'final' : 'preview'
      const job = enqueue(state, project, found.shot, found.sceneId, kind)
      tickQueue(state)
      return { status: 'queued', version_number: job.version_number, warnings: [] }
    }),
  )

  router.post('/api/film/projects/:projectId/generate/batch', req =>
    store.mutate(state => {
      const project = store.ensureProject(req.params.projectId)
      const kind: VersionKind = req.body.kind === 'final' ? 'final' : 'preview'
      const sceneId = typeof req.body.scene_id === 'string' ? req.body.scene_id : ''
      const shotIds = Array.isArray(req.body.shot_ids) ? (req.body.shot_ids as string[]) : []

      const targets: { sceneId: string; shot: FilmShot }[] = []
      for (const scene of project.scenes) {
        if (sceneId && scene.id !== sceneId) continue
        for (const shot of scene.shots) {
          if (shotIds.length > 0 && !shotIds.includes(shot.id)) continue
          targets.push({ sceneId: scene.id, shot })
        }
      }

      const queued = targets.map(t => enqueue(state, project, t.shot, t.sceneId, kind))
      tickQueue(state)
      return {
        status: 'queued',
        queued: queued.map(({ project_id, scene_id, shot_id, shot_title, kind: k, version_number, status }) => ({
          project_id,
          scene_id,
          shot_id,
          shot_title,
          kind: k,
          version_number,
          status,
        })),
      }
    }),
  )

  router.get('/api/film/queue', () => queueSnapshot(store.data))

  router.post('/api/film/queue/pause', () =>
    store.mutate(state => {
      state.queue.paused = true
      return { status: 'ok', queue: queueSnapshot(state) }
    }),
  )

  router.post('/api/film/queue/resume', () =>
    store.mutate(state => {
      state.queue.paused = false
      tickQueue(state)
      return { status: 'ok', queue: queueSnapshot(state) }
    }),
  )

  router.post('/api/film/queue/cancel', () =>
    store.mutate(state => {
      for (const job of state.queue.pending) finish(state, job, 'cancelled')
      state.queue.pending = []
      if (state.queue.active) {
        finish(state, state.queue.active, 'cancelled')
        state.queue.active = null
      }
      return queueSnapshot(state)
    }),
  )

  router.post('/api/film/queue/:shotId/cancel', req =>
    store.mutate(state => {
      const shotId = req.params.shotId
      const pending = state.queue.pending.find(job => job.shot_id === shotId)
      if (pending) {
        state.queue.pending = state.queue.pending.filter(job => job !== pending)
        finish(state, pending, 'cancelled')
      } else if (state.queue.active?.shot_id === shotId) {
        finish(state, state.queue.active, 'cancelled')
        state.queue.active = null
      }
      tickQueue(state)
      return { status: 'ok', queue: queueSnapshot(state) }
    }),
  )

  router.post('/api/film/queue/:shotId/prioritize', req =>
    store.mutate(state => {
      const index = state.queue.pending.findIndex(job => job.shot_id === req.params.shotId)
      if (index > 0) {
        const [job] = state.queue.pending.splice(index, 1)
        state.queue.pending.unshift(job)
      }
      return { status: 'ok', queue: queueSnapshot(state) }
    }),
  )
}

export { jobProgress }
