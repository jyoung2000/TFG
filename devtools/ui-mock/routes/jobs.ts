/**
 * The unified job store, simulated.
 *
 * Three finished jobs of every kind plus one that is rendering right now: its
 * progress derives from wall-clock time, so History's live update path is
 * exercised whenever the UI polls. There is no SSE here (the mock cannot
 * stream), so `/api/jobs/events` answers 404 and the renderer falls back to
 * polling — which is exactly what the desktop app does when a stream fails.
 */

import type { Job, JobKind, JobOutput, JobStatus, LegacyQuickEntry } from '../../../frontend/types/jobs'
import { MockHttpError, type Router } from '../http'
import { DEMO_OUTPUT } from '../seed'
import type { MockState, Store } from '../state'

const RUNNING_MS = 20_000
const KINDS: JobKind[] = ['image_gen', 'video_gen', 'image_reproduce', 'video_reproduce', 'analysis', 'scene_build', 'training', 'download']

const PROMPTS = [
  'Mara crouches at the dead console, torchlight on frost',
  'The ridge at dawn, wind pulling snow off the crest',
  'Close on the antenna array, amber strip light flickering',
]

function output(kind: JobOutput['kind'], name: string, index: number): JobOutput {
  const isVideo = kind === 'video'
  return {
    path: isVideo ? DEMO_OUTPUT : `ui-mock/outputs/${name}-${index}.png`,
    kind,
    width: isVideo ? 960 : 1024,
    height: isVideo ? 544 : 576,
    duration: isVideo ? 5.0 : 0,
    thumb: `ui-mock/jobs/thumbs/${name}-${index}.jpg`,
  }
}

function job(kind: JobKind, index: number, status: JobStatus, minutesAgo: number, extra: Partial<Job> = {}): Job {
  const created = Date.now() - minutesAgo * 60_000
  const name = `${kind}-${index}`
  const videoKinds: JobKind[] = ['video_gen', 'video_reproduce', 'scene_build']
  const outputs: JobOutput[] =
    status === 'complete'
      ? kind === 'download'
        ? [{ path: `ui-mock/models/${name}.safetensors`, kind: 'file', width: 0, height: 0, duration: 0, thumb: '' }]
        : [output(videoKinds.includes(kind) ? 'video' : 'image', name, 1)]
      : []
  if (status === 'complete' && kind === 'image_gen') outputs.push(output('image', name, 2))
  return {
    id: `job_${name}`,
    kind,
    status,
    progress: status === 'complete' ? 100 : status === 'failed' ? 62 : 0,
    phase: status === 'complete' ? 'complete' : status === 'failed' ? 'failed' : '',
    title: kind === 'download' ? `ltx2-${index}-int8.safetensors` : PROMPTS[index % PROMPTS.length],
    created_at: created,
    updated_at: status === 'queued' || status === 'running' ? created : created + 30_000,
    started_at: status === 'queued' ? null : created,
    finished_at: status === 'queued' || status === 'running' ? null : created + 30_000,
    model: kind === 'download' ? 'Lightricks/LTX-2' : kind.startsWith('image') ? 'z_image' : 'ltx2_22B_distilled',
    provider: kind === 'download' ? 'huggingface' : 'wangp',
    seed: 1000 + index,
    prompt: kind === 'download' ? '' : PROMPTS[index % PROMPTS.length],
    negative_prompt: kind === 'download' ? '' : 'blurry, text, watermark',
    spec: {},
    params: kind === 'download' ? { files: [`${name}.safetensors`] } : { resolution: '540p', duration: '5', fps: '24', model: 'fast', aspectRatio: '16:9' },
    inputs: kind === 'analysis' || kind.endsWith('reproduce') ? { analysis_id: `va-${index}`, video_path: `C:/clips/reference-${index}.mp4` } : {},
    outputs,
    metrics:
      status === 'complete'
        ? kind === 'training'
          ? { loss_history: Array.from({ length: 40 }, (_, i) => Number((0.6 * (1 - i / 40) + 0.05 + Math.sin(i / 5) * 0.02).toFixed(4))), final_loss: 0.071, steps: 600, seconds: 760 + index, peak_vram_mb: 10850 }
          : kind === 'video_gen' && index === 1
            ? { seconds: 28.4 + index, peak_vram_mb: 9800 + index * 100, consistency: 0.82 }
            : { seconds: 28.4 + index, peak_vram_mb: 9800 + index * 100 }
        : {},
    parent_job_id: '',
    project_id: '',
    shot_id: '',
    error: status === 'failed' ? 'CUDA out of memory: free 2.1 GB (qwen2.5vl:3b is loaded)' : '',
    ...extra,
  }
}

export function seedJobs(): Job[] {
  const jobs: Job[] = []
  let minutes = 5
  for (const kind of KINDS) {
    for (let index = 1; index <= 3; index++) {
      const status: JobStatus = index === 3 && kind === 'video_gen' ? 'failed' : 'complete'
      jobs.push(job(kind, index, status, minutes))
      minutes += 7
    }
  }
  // A child candidate under a reproduce parent, so lineage renders.
  jobs.push(job('image_gen', 9, 'complete', 12, { parent_job_id: 'job_image_reproduce-1', title: 'candidate 1 of 6' }))
  // The live one: a film shot rendering right now.
  jobs.push(
    job('video_gen', 7, 'running', 0, {
      title: 'Mara at the console · v2 (final)',
      project_id: 'ui-mock-film',
      shot_id: 'shot-1-2',
      started_at: Date.now(),
      phase: 'inference',
    }),
  )
  jobs.push(job('video_gen', 8, 'queued', 0, { title: 'The console answers · v1 (preview)', project_id: 'ui-mock-film', shot_id: 'shot-1-3' }))
  return jobs
}

/** Advance the running job by wall-clock time; finish it after RUNNING_MS. */
export function tickJobs(state: MockState): void {
  for (const item of state.historyJobs) {
    if (item.status !== 'running' || !item.started_at) continue
    // Link LoRA downloads advance in tickLoraDownloads (routes/training.ts).
    if (item.kind === 'download' && item.inputs.lora_url) continue
    const elapsed = Date.now() - item.started_at
    if (elapsed >= RUNNING_MS) {
      item.status = 'complete'
      item.progress = 100
      item.phase = 'complete'
      item.finished_at = Date.now()
      item.outputs = [output('video', item.id, 1)]
      item.metrics = { seconds: RUNNING_MS / 1000, peak_vram_mb: 10240 }
      // The next queued job starts.
      const next = state.historyJobs.find(j => j.status === 'queued')
      if (next) {
        next.status = 'running'
        next.started_at = Date.now()
        next.phase = 'loading_model'
      }
    } else {
      item.progress = Math.min(99, Math.round((elapsed / RUNNING_MS) * 100))
      item.phase = elapsed < 3000 ? 'loading_model' : elapsed < 5000 ? 'encoding_text' : 'inference'
    }
    item.updated_at = Date.now()
  }
}

function find(state: MockState, id: string): Job {
  const found = state.historyJobs.find(j => j.id === id)
  if (!found) throw new MockHttpError(404, `Unknown job: ${id}`)
  return found
}

export function registerJobRoutes(router: Router, store: Store): void {
  router.get('/api/jobs', req => {
    const kind = req.query.get('kind') ?? ''
    const status = req.query.get('status') ?? ''
    const project = req.query.get('project') ?? ''
    const q = (req.query.get('q') ?? '').toLowerCase()
    const limit = Number(req.query.get('limit') ?? 50)
    const jobs = store.data.historyJobs
      .filter(j => !kind || j.kind === kind)
      .filter(j => !status || (status === 'active' ? j.status === 'queued' || j.status === 'running' : j.status === status))
      .filter(j => !project || j.project_id === project)
      .filter(j => !q || `${j.prompt} ${j.title} ${j.model}`.toLowerCase().includes(q))
      .sort((a, b) => b.created_at - a.created_at)
    return { jobs: jobs.slice(0, limit), next_cursor: '' }
  })

  router.get('/api/jobs/events', () => {
    throw new MockHttpError(404, 'The UI mock does not stream; the renderer polls instead')
  })

  router.post('/api/jobs/import', req => {
    const body = req.body as { entries?: LegacyQuickEntry[] }
    let imported = 0
    store.mutate(state => {
      for (const entry of body.entries ?? []) {
        if (state.historyJobs.some(j => j.outputs.some(o => o.path === entry.video_path))) continue
        state.historyJobs.push(
          job('video_gen', 100 + imported, 'complete', 0, {
            id: `job_imported-${imported}`,
            title: entry.prompt.slice(0, 80),
            prompt: entry.prompt,
            negative_prompt: entry.negative_prompt ?? '',
            seed: entry.seed ?? null,
            created_at: entry.created_at || Date.now(),
            params: entry.params ?? {},
            inputs: { imported_from: 'ltx-quick-history' },
          }),
        )
        imported++
      }
    })
    return { imported, skipped: (body.entries?.length ?? 0) - imported }
  })

  router.get('/api/jobs/:id', req => {
    const current = find(store.data, req.params.id)
    const lineage: Job[] = []
    let cursor: Job | undefined = current
    const seen = new Set<string>()
    while (cursor && !seen.has(cursor.id)) {
      lineage.unshift(cursor)
      seen.add(cursor.id)
      const parentId: string = cursor.parent_job_id
      cursor = parentId ? store.data.historyJobs.find(j => j.id === parentId) : undefined
    }
    const children = store.data.historyJobs.filter(j => j.parent_job_id === current.id)
    return { job: current, lineage, children }
  })

  router.delete('/api/jobs/:id', req => {
    const current = find(store.data, req.params.id)
    if (current.status === 'queued' || current.status === 'running') throw new MockHttpError(409, 'Cancel the job before deleting it')
    const files = req.query.get('files') === 'true'
    store.mutate(state => {
      state.historyJobs = state.historyJobs.filter(j => j.id !== current.id)
    })
    return { deleted: true, removed_files: files ? current.outputs.map(o => o.path) : [] }
  })

  router.post('/api/jobs/:id/cancel', req =>
    store.mutate(state => {
      const current = find(state, req.params.id)
      if (current.status === 'queued' || current.status === 'running') {
        current.status = 'cancelled'
        current.phase = 'cancelled'
        current.error = 'Cancelled'
        current.finished_at = Date.now()
        current.updated_at = Date.now()
      }
      return current
    }),
  )

  router.post('/api/jobs/:id/rerun', req =>
    store.mutate(state => {
      const source = find(state, req.params.id)
      if (source.kind !== 'video_gen' && source.kind !== 'image_gen') throw new MockHttpError(400, `${source.kind} jobs cannot be re-run from History`)
      const copy: Job = {
        ...source,
        id: `job_rerun-${Date.now().toString(36)}`,
        status: 'running',
        progress: 0,
        phase: 'loading_model',
        created_at: Date.now(),
        updated_at: Date.now(),
        started_at: Date.now(),
        finished_at: null,
        outputs: [],
        metrics: {},
        error: '',
        parent_job_id: source.id,
      }
      state.historyJobs.push(copy)
      return copy
    }),
  )
}
