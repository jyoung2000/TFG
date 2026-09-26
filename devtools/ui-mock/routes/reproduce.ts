/**
 * Image Reproduce v2, simulated.
 *
 * Import accepts any path the browser file-dialog shim hands back (it only
 * knows how to pretend), analysis fills a ShotSpec with mock evidence, and
 * `start` runs a wall-clock loop: one round every few seconds, each adding
 * candidates whose composite score climbs towards the target. Media are
 * SVG placeholders clearly marked as mock. Prompts are compiled with the
 * renderer's own preview formatter so the mock never drifts from the
 * contract in `frontend/types/shotspec.ts`.
 */

import type { PromptStyle, ShotSpec, SpecCompileResult } from '../../../frontend/types/shotspec'
import type { ReproduceBudget, ReproduceCandidate, ReproduceJob, ReproduceRound } from '../../../frontend/types/reproduce'
import { emptySpec } from '../../../frontend/lib/shotspec/schema'
import { previewPrompt, isStillTarget } from '../../../frontend/lib/shotspec/formatters'
import { MockHttpError, RawResponse, type Router } from '../http'
import { placeholderSvg } from '../media'
import type { MockState, Store } from '../state'

const ROUND_MS = 2_500
const SEED0 = 1234
let serial = 0
/** When each running loop started, by job id (not part of the contract). */
const origins = new Map<string, number>()

function mockSpec(width: number, height: number): ShotSpec {
  const spec = emptySpec('image')
  spec.source = { kind: 'image', hash: 'mock-hash', path: 'reference.png', width, height, aspect: '16:9', fps: null, start: null, end: null }
  spec.measured = { palette: [{ hex: '#3a2a20', share: 0.62 }, { hex: '#e6be78', share: 0.21 }, { hex: '#5a3c2d', share: 0.17 }], luminance: 0.31, contrast: 0.22, saturation: 0.41, edge_density: 0.08, sharpness: 0.0021, exif: {} }
  spec.subjects = [
    { label: 'person', bbox: [0.28, 0.25, 0.16, 0.7], depth_median: 0.71, count: 1, attributes: ['crouching'] },
    { label: 'window', bbox: [0.7, 0.11, 0.22, 0.39], depth_median: 0.2, count: 1, attributes: [] },
  ]
  spec.scene = { location: 'dim control room', environment: 'interior', time_of_day: 'night', weather: '', fg: 'dead console', mg: 'crouching person', bg: 'warm window' }
  spec.camera = { shot_size: 'full', angle: 'eye level', height: 'eye', fov_deg: 46, focal_mm: 40, lens_estimate: '40mm', aperture: 'f/2.8', dof: 'shallow', focus: 'person', move: 'static', move_intensity: 0, handheld: false, roll: 0 }
  spec.lighting = { key_direction: 'window right', quality: 'soft', color_temp: 'warm', mood: 'moody' }
  spec.style = { tags: [{ term: 'photograph', score: 0.31 }, { term: 'cinematic', score: 0.28 }, { term: 'warm lighting', score: 0.27 }], medium: 'photograph', artists: [], negatives: ['blurry'] }
  spec.narrative = { what_happens: 'A person crouches at a dead console.', purpose: '', beat: '' }
  spec.confidence = { measured: 1, subjects: 0.9, scene: 0.6, camera: 0.6, lighting: 0.7, style: 0.5 }
  spec.provenance = { measured: 'measured', subjects: 'florence', scene: 'vlm', camera: 'depth', lighting: 'vlm', style: 'clip' }
  return spec
}

function compiled(spec: ShotSpec, target: string, style: PromptStyle | null): { prompt: string; negative_prompt: string; style: PromptStyle } {
  const resolved: PromptStyle = style ?? (isStillTarget(target) ? 'tagged' : 'narrative')
  return { ...previewPrompt(spec, target, resolved), style: resolved }
}

function resultFor(spec: ShotSpec, target: string, style: PromptStyle): SpecCompileResult {
  const still = isStillTarget(target)
  const { prompt, negative_prompt } = previewPrompt(spec, target, style)
  return {
    target_id: target,
    target_label: target,
    style,
    prompt,
    negative_prompt,
    params: { seed: null, steps: still ? 28 : 8, guidance: still ? 4 : 3, width: 1280, height: 720, duration: still ? 0 : 5, fps: still ? 0 : 24, resolution: '720p' },
    conditioning: { start_frame: '', control_video: '', depth: '', refs: [], loras: [] },
    dropped: still ? ['motion'] : [],
    hints_applied: [],
    matched: true,
  }
}

function find(state: MockState, id: string): ReproduceJob {
  const job = state.reproduceJobs.find(item => item.id === id)
  if (!job) throw new MockHttpError(404, 'Reproduce job not found')
  return job
}

function scores(composite: number): ReproduceCandidate['scores'] {
  return {
    composite,
    components: { clip: composite + 0.05, dino: composite - 0.03, ssim: composite - 0.1, palette: composite + 0.08, layout: composite },
    weights_used: { clip: 0.35, dino: 0.25, ssim: 0.15, palette: 0.15, layout: 0.1 },
    missing: [],
  }
}

function bestOf(job: ReproduceJob): ReproduceCandidate | null {
  return job.candidates.reduce<ReproduceCandidate | null>((best, c) => (best === null || c.scores.composite > best.scores.composite ? c : best), null)
}

/** Advance a running loop to the present. */
export function tickReproduce(state: MockState): void {
  const now = Date.now()
  for (const job of state.reproduceJobs) {
    if (job.status !== 'rendering' && job.status !== 'scoring') continue
    const startedAt = origins.get(job.id) ?? job.updated_at
    const elapsedRounds = Math.floor((now - startedAt) / ROUND_MS)
    const total = job.budget.max_rounds
    while (job.rounds.length <= elapsedRounds && job.rounds.length < total) {
      const index = job.rounds.length + 1
      const round: ReproduceRound = {
        index,
        prompt: job.prompt,
        negative_prompt: job.negative_prompt,
        target: job.target,
        style: job.style ?? 'narrative',
        hints_applied: index > 1 ? ['warm window light'] : [],
        patches: index > 1 ? [{ reason: 'palette below 0.6', phrase: 'warm amber tones', metric: 'palette', value: 0.55 }] : [],
        seeds: [],
        best_candidate_id: '',
        best_score: 0,
        started_at: startedAt + (index - 1) * ROUND_MS,
        finished_at: startedAt + index * ROUND_MS,
        note: 'UI mock round — no model ran',
      }
      for (let n = 0; n < job.budget.candidates_per_round; n++) {
        const seed = SEED0 + (index - 1) * 100 + n
        const composite = Math.min(0.98, 0.45 + index * 0.12 + n * 0.03)
        const candidate: ReproduceCandidate = {
          id: `r${index}-c${n + 1}`,
          path: `round${index}/candidate-${n + 1}.png`,
          prompt: job.prompt,
          negative_prompt: job.negative_prompt,
          seed,
          params: { steps: 28, guidance: 4, width: job.width, height: job.height },
          round: index,
          model: job.image_model,
          target: job.target,
          scores: scores(composite),
          job_id: `job_${job.id}_${index}_${n + 1}`,
          source: 'render',
          parent_id: '',
          created_at: round.finished_at ?? now,
        }
        job.candidates.push(candidate)
        round.seeds.push(seed)
        if (composite > round.best_score) { round.best_score = composite; round.best_candidate_id = candidate.id }
      }
      job.rounds.push(round)
      const best = bestOf(job)
      job.best_candidate_id = best?.id ?? ''
      job.updated_at = now
      if ((best?.scores.composite ?? 0) >= job.budget.target_score) break
    }
    const best = bestOf(job)
    const done = job.rounds.length >= total || (best?.scores.composite ?? 0) >= job.budget.target_score
    if (done && job.rounds.length > 0 && now >= (job.rounds.at(-1)?.finished_at ?? now)) {
      job.status = 'complete'
      job.progress = 100
      job.message = `best ${((best?.scores.composite ?? 0) * 100).toFixed(0)}% after ${job.rounds.length} round${job.rounds.length === 1 ? '' : 's'}`
    } else {
      job.progress = Math.min(99, Math.round(((now - startedAt) / (total * ROUND_MS)) * 100))
      job.message = `round ${Math.min(job.rounds.length + 1, total)} of ${total}`
    }
  }
}

export function registerReproduceRoutes(router: Router, store: Store): void {
  const compileBody = (body: Record<string, unknown>) => {
    const spec = (body.spec as ShotSpec | undefined) ?? emptySpec('image')
    const targets: string[] = Array.isArray(body.targets) && body.targets.length ? (body.targets as string[]) : ['z_image']
    const styles: PromptStyle[] = Array.isArray(body.styles) && body.styles.length ? (body.styles as PromptStyle[]) : ['narrative']
    return { spec, targets, styles }
  }

  router.post('/api/prompts/compile-spec', req => {
    const { spec, targets, styles } = compileBody(req.body)
    return resultFor(spec, targets[0], styles[0])
  })

  router.post('/api/prompts/compile-spec/all', req => {
    const { spec, targets, styles } = compileBody(req.body)
    const results: Record<string, SpecCompileResult> = {}
    for (const target of targets) for (const style of styles) results[`${target}:${style}`] = resultFor(spec, target, style)
    return { results, hints: null }
  })

  router.get('/api/reproduce', () => store.mutate(state => { tickReproduce(state); return { jobs: state.reproduceJobs } }))

  router.post('/api/reproduce/import', req => {
    const path = String(req.body.path ?? '').trim()
    if (!path) throw new MockHttpError(400, 'path is required')
    const title = path.split(/[\\/]/).pop() || 'Reference'
    const now = Date.now()
    const job: ReproduceJob = {
      version: 2,
      id: `rp-mock-${++serial}`,
      title,
      source_path: 'reference.png',
      width: 1280,
      height: 720,
      spec: emptySpec('image'),
      target: 'z_image',
      style: null,
      prompt_override: '',
      prompt: '',
      negative_prompt: '',
      image_model: 'z_image (UI mock)',
      loras: [],
      vision_model: '',
      budget: { candidates_per_round: 2, max_rounds: 3, target_score: 0.85 },
      status: 'idle',
      progress: 0,
      message: '',
      error: '',
      candidates: [],
      rounds: [],
      best_candidate_id: '',
      reference_candidate_id: '',
      picked_candidate_id: '',
      why: {},
      depth_path: '',
      job_id: '',
      created_at: now,
      updated_at: now,
    }
    store.mutate(state => { state.reproduceJobs.unshift(job) })
    return job
  })

  router.get('/api/reproduce/:id', req => store.mutate(state => { tickReproduce(state); return find(state, req.params.id) }))

  router.delete('/api/reproduce/:id', req => {
    store.mutate(state => { state.reproduceJobs = state.reproduceJobs.filter(job => job.id !== req.params.id) })
    return { status: 'ok' }
  })

  router.post('/api/reproduce/:id/analyze', req => store.mutate(state => {
    const job = find(state, req.params.id)
    job.spec = mockSpec(job.width, job.height)
    job.vision_model = 'UI mock (not a model)'
    job.depth_path = 'depth.png'
    job.why = {
      measured: { aspect: '16:9', luminance: 0.31, contrast: 0.22, saturation: 0.41, edge_density: 0.08, sharpness: 0.0021, palette: job.spec.measured.palette },
      subjects: { source: 'florence-2-large', regions: job.spec.subjects.map(s => ({ label: s.label, bbox: s.bbox, depth_median: s.depth_median })) },
      caption: { source: 'florence-2-large', text: 'A person crouches at a console in a dim room lit by a warm window.' },
      style: { source: 'clip-vit-large-patch14', tags: job.spec.style.tags.map(t => ({ ...t, category: 'flavor' })), negatives: ['blurry'] },
      depth: { source: 'depth-anything-v2-small', near: 1, far: 0, mean: 0.45 },
      notes: { mock: 'UI mock evidence — no model ran' },
    }
    const c = compiled(job.spec, job.target, job.style)
    job.prompt = c.prompt
    job.negative_prompt = c.negative_prompt
    job.status = 'idle'
    job.message = 'analysed'
    job.updated_at = Date.now()
    return job
  }))

  router.put('/api/reproduce/:id/spec', req => store.mutate(state => {
    const job = find(state, req.params.id)
    const sections = (req.body.sections as Partial<ShotSpec> | undefined) ?? {}
    const locks = (req.body.locks as Record<string, boolean> | undefined) ?? {}
    for (const [section, value] of Object.entries(sections)) {
      ;(job.spec as unknown as Record<string, unknown>)[section] = value
      job.spec.provenance[section] = 'user'
      job.spec.locks[section] = true
    }
    for (const [section, locked] of Object.entries(locks)) job.spec.locks[section] = locked
    if (!job.prompt_override) {
      const c = compiled(job.spec, job.target, job.style)
      job.prompt = c.prompt
      job.negative_prompt = c.negative_prompt
    }
    job.updated_at = Date.now()
    return job
  }))

  router.put('/api/reproduce/:id/prompt', req => store.mutate(state => {
    const job = find(state, req.params.id)
    if (typeof req.body.target === 'string' && req.body.target) job.target = req.body.target
    if (req.body.style === null || typeof req.body.style === 'string') job.style = (req.body.style as PromptStyle | null) ?? null
    job.prompt_override = String(req.body.prompt ?? '').trim()
    const c = compiled(job.spec, job.target, job.style)
    job.prompt = job.prompt_override || c.prompt
    job.negative_prompt = c.negative_prompt
    job.updated_at = Date.now()
    return job
  }))

  router.post('/api/reproduce/:id/start', req => store.mutate(state => {
    tickReproduce(state)
    const job = find(state, req.params.id)
    if (job.status === 'rendering' || job.status === 'scoring') throw new MockHttpError(409, 'The loop is already running')
    if (!job.prompt) throw new MockHttpError(400, 'Analyse the reference or write a prompt first')
    const budget = req.body.budget as Partial<ReproduceBudget> | undefined
    if (budget) job.budget = { ...job.budget, ...budget }
    job.candidates = []
    job.rounds = []
    job.best_candidate_id = ''
    job.status = 'rendering'
    job.progress = 0
    job.message = 'round 1 of ' + job.budget.max_rounds
    job.error = ''
    job.job_id = `job_${job.id}`
    origins.set(job.id, Date.now())
    job.updated_at = Date.now()
    return job
  }))

  router.post('/api/reproduce/:id/cancel', req => store.mutate(state => {
    tickReproduce(state)
    const job = find(state, req.params.id)
    if (job.status === 'rendering' || job.status === 'scoring') {
      job.status = 'cancelled'
      job.message = 'cancelled'
      job.updated_at = Date.now()
    }
    return job
  }))

  router.post('/api/reproduce/:id/pin/:candidate', req => store.mutate(state => {
    const job = find(state, req.params.id)
    const cid = req.params.candidate === 'source' ? '' : req.params.candidate
    if (cid && !job.candidates.some(c => c.id === cid)) throw new MockHttpError(404, 'Candidate not found')
    job.reference_candidate_id = cid
    job.updated_at = Date.now()
    return job
  }))

  router.post('/api/reproduce/:id/pick/:candidate', req => store.mutate(state => {
    const job = find(state, req.params.id)
    if (!job.candidates.some(c => c.id === req.params.candidate)) throw new MockHttpError(404, 'Candidate not found')
    job.picked_candidate_id = req.params.candidate
    job.updated_at = Date.now()
    return job
  }))

  router.post('/api/reproduce/:id/candidates/:candidate/fix', req => store.mutate(state => {
    const job = find(state, req.params.id)
    const parent = job.candidates.find(c => c.id === req.params.candidate)
    if (!parent) throw new MockHttpError(404, 'Candidate not found')
    if (typeof req.body.inpaint_prompt === 'string' && req.body.inpaint_prompt.trim()) {
      throw new MockHttpError(501, 'Inpainting needs the WanGP image-edit model; not available in the UI mock')
    }
    const index = job.candidates.length + 1
    const fixed: ReproduceCandidate = {
      ...parent,
      id: `fix-${index}`,
      path: `fixes/candidate-${index}.png`,
      params: { ...parent.params, fix: req.body },
      scores: scores(Math.min(0.99, parent.scores.composite + 0.02)),
      source: req.body.patch_from_reference ? 'patch' : 'fix',
      parent_id: parent.id,
      created_at: Date.now(),
    }
    job.candidates.push(fixed)
    job.best_candidate_id = bestOf(job)?.id ?? job.best_candidate_id
    job.updated_at = Date.now()
    return job
  }))

  router.get('/api/reproduce/:id/media', req => {
    const job = find(store.data, req.params.id)
    const path = req.query.get('path') ?? ''
    const known = path === job.source_path || path === job.depth_path || job.candidates.some(c => c.path === path)
    if (!path || !known) throw new MockHttpError(400, 'Invalid media path')
    const label = path === job.source_path ? 'Reference (UI MOCK)' : path === job.depth_path ? 'Depth (UI MOCK)' : 'Candidate (UI MOCK)'
    return new RawResponse(200, { 'content-type': 'image/svg+xml', 'cache-control': 'no-store' }, placeholderSvg(label, `${job.title} · ${path}`, `${job.id}/${path}`))
  })
}
