/**
 * LoRA training, simulated: datasets that accept any import, Florence-style
 * captions with the trigger word, a run that steps on the wall clock with a
 * falling loss curve and sample images, cancel/resume, and a registry the
 * pickers read. Images are labelled SVG placeholders.
 */

import type { Dataset, DatasetItem, DatasetPreset, LoraEntry, TrainingConfig, TrainingRun, TrainingStatusResponse } from '../../../frontend/types/training'
import type { Job } from '../../../frontend/types/jobs'
import { MockHttpError, type Router } from '../http'
import { placeholderFrame } from '../media'
import type { MockState, Store } from '../state'

const STEP_MS = 120
const MACHINE_VRAM_MB = 12288
let serial = 0
const id = (prefix: string) => `${prefix}-mock${(serial += 1).toString().padStart(4, '0')}`

const TRAINERS: TrainingStatusResponse['trainers'] = [
  { id: 'musubi', name: 'musubi-tuner', upstream: 'kohya-ss/musubi-tuner', license: 'Apache-2.0', targets: ['z_image', 'qwen_image', 'flux', 'wan22'], installed: true, fits_12gb: true, reason: 'musubi-tuner ready in backend/.venv-trainer-musubi', notes: '' },
  { id: 'ai-toolkit', name: 'ai-toolkit', upstream: 'ostris/ai-toolkit', license: 'MIT', targets: ['flux', 'z_image', 'qwen_image'], installed: false, fits_12gb: true, reason: 'ai-toolkit is not installed. Run `scripts/ensure-trainer.sh ai-toolkit`.', notes: '' },
  { id: 'ltx-trainer', name: 'LTX-2 trainer', upstream: 'Lightricks/LTX-2', license: 'Apache-2.0', targets: ['ltx2'], installed: false, fits_12gb: false, reason: 'LTX-2 trainer needs ~32 GB of VRAM; this machine has 12 GB.', notes: 'Upstream recommends 80 GB; the low-VRAM config targets 32 GB.' },
]

const BASE: Record<string, Pick<TrainingConfig, 'trainer' | 'rank' | 'steps' | 'resolution' | 'buckets' | 'blocks_to_swap' | 'estimated_vram_mb'>> = {
  z_image: { trainer: 'musubi', rank: 16, steps: 600, resolution: 768, buckets: [512, 768], blocks_to_swap: 8, estimated_vram_mb: 10500 },
  qwen_image: { trainer: 'musubi', rank: 16, steps: 800, resolution: 768, buckets: [512, 768], blocks_to_swap: 20, estimated_vram_mb: 11200 },
  flux: { trainer: 'ai-toolkit', rank: 16, steps: 1000, resolution: 768, buckets: [512, 768, 1024], blocks_to_swap: 0, estimated_vram_mb: 11500 },
  wan22: { trainer: 'musubi', rank: 16, steps: 800, resolution: 512, buckets: [384, 512], blocks_to_swap: 30, estimated_vram_mb: 24000 },
  ltx2: { trainer: 'ltx-trainer', rank: 32, steps: 1000, resolution: 512, buckets: [512], blocks_to_swap: 0, estimated_vram_mb: 32768 },
}

function suggest(target: string, preset: DatasetPreset, imageCount: number): TrainingConfig {
  const base = BASE[target] ?? BASE.z_image
  const rankDelta = preset === 'style' ? 8 : preset === 'object' ? -4 : 0
  const scale = preset === 'style' ? 1.5 : preset === 'object' ? 0.8 : 1
  const steps = Math.max(200, Math.min(3000, Math.round(base.steps * scale * Math.max(0.6, Math.min(2, imageCount / 12)))))
  return {
    target,
    trainer: base.trainer,
    rank: Math.max(4, base.rank + rankDelta),
    steps,
    learning_rate: preset === 'style' ? 8e-5 : preset === 'object' ? 1.2e-4 : 1e-4,
    batch_size: 1,
    resolution: base.resolution,
    buckets: base.buckets,
    blocks_to_swap: base.blocks_to_swap,
    fp8: true,
    save_every: Math.max(50, Math.floor(steps / 6)),
    sample_every: Math.max(50, Math.floor(steps / 6)),
    seed: 42,
    estimated_vram_mb: base.estimated_vram_mb,
  }
}

function withTrigger(caption: string, trigger: string, preset: DatasetPreset): string {
  const t = trigger.trim()
  if (!t || caption.toLowerCase().includes(t.toLowerCase())) return caption
  return preset === 'style' ? `${caption}, in the style of ${t}` : `${t}, ${caption}`
}

function item(file: string, source: DatasetItem['source'], origin: string): DatasetItem {
  return { id: id('item'), file, caption: '', edited: false, source, origin, width: 1024, height: 768 }
}

function dataset(state: MockState, datasetId: string): Dataset {
  const found = state.training.datasets.find(d => d.id === datasetId)
  if (!found) throw new MockHttpError(404, 'Dataset not found')
  return found
}

function run(state: MockState, runId: string): TrainingRun {
  const found = state.training.runs.find(r => r.id === runId)
  if (!found) throw new MockHttpError(404, 'Training run not found')
  return found
}

function trainingJob(state: MockState, r: TrainingRun): Job | undefined {
  return state.historyJobs.find(j => j.id === r.job_id)
}

// ---- LoRA downloads from a link -------------------------------------------------------------

const DOWNLOAD_MS = 1500
const DOWNLOAD_BYTES = 24_117_248 // 23 MB

/** Mirror of the backend's `parse_lora_url` rejections, same messages. */
function parseLoraLink(raw: string): { provider: 'huggingface' | 'civitai' | 'direct'; filename: string } {
  let url: URL
  try {
    url = new URL(raw.trim())
  } catch {
    throw new MockHttpError(400, 'Paste an https:// link from Hugging Face or Civitai, or a direct .safetensors URL')
  }
  if (url.protocol !== 'https:') throw new MockHttpError(400, 'Paste an https:// link from Hugging Face or Civitai, or a direct .safetensors URL')
  const host = url.hostname.toLowerCase()
  const last = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() ?? '')
  if (['huggingface.co', 'www.huggingface.co', 'hf.co'].includes(host)) {
    if (!/\/(blob|resolve)\//.test(url.pathname)) throw new MockHttpError(400, 'That Hugging Face link is a repo page — open the .safetensors file and copy the link to the file itself')
    if (!last.toLowerCase().endsWith('.safetensors')) throw new MockHttpError(400, 'The Hugging Face link must point at a .safetensors file inside the repo (open the file page and copy its URL)')
    return { provider: 'huggingface', filename: last }
  }
  if (['civitai.com', 'www.civitai.com'].includes(host)) {
    const model = url.pathname.match(/^\/models\/(\d+)/)
    const direct = url.pathname.match(/^\/api\/download\/models\/(\d+)/)
    if (!model && !direct) throw new MockHttpError(400, 'That Civitai link is not a model page or a download link (expected civitai.com/models/<id> or /api/download/models/<id>)')
    return { provider: 'civitai', filename: `civitai-${(model ?? direct)![1]}.safetensors` }
  }
  if (last.toLowerCase().endsWith('.safetensors')) return { provider: 'direct', filename: last }
  throw new MockHttpError(400, 'Only Hugging Face links, Civitai links, or direct .safetensors URLs are supported')
}

/** Advance running link downloads; register the LoRA when one lands. */
export function tickLoraDownloads(state: MockState): void {
  const now = Date.now()
  for (const job of state.historyJobs) {
    if (job.kind !== 'download' || !job.inputs.lora_url || job.status !== 'running' || !job.started_at) continue
    const elapsed = now - job.started_at
    if (elapsed < DOWNLOAD_MS) {
      const done = Math.round((elapsed / DOWNLOAD_MS) * DOWNLOAD_BYTES)
      job.progress = Math.min(99, Math.round((elapsed / DOWNLOAD_MS) * 100))
      job.phase = `downloading · ${(done / 1_048_576).toFixed(1)} / ${(DOWNLOAD_BYTES / 1_048_576).toFixed(1)} MB`
    } else {
      const target = String(job.params.target ?? 'z_image')
      const filename = String(job.params.filename ?? 'lora.safetensors')
      const file = `C:/Users/you/AppData/Roaming/ltx-desktop/loras/${target}/${filename}`
      const entry: LoraEntry = {
        id: id('lora'),
        name: String(job.params.name ?? '') || filename.replace(/\.safetensors$/i, ''),
        file,
        target,
        base_model: target,
        trigger: String(job.params.trigger ?? ''),
        dataset_id: '',
        run_id: '',
        job_id: job.id,
        preset: 'character',
        default_multiplier: 1,
        size_bytes: DOWNLOAD_BYTES,
        imported: true,
        created_at: now,
      }
      state.training.loras = [entry, ...state.training.loras.filter(l => l.file !== file)]
      job.status = 'complete'
      job.progress = 100
      job.phase = 'complete'
      job.finished_at = now
      job.outputs = [{ path: file, kind: 'file', width: 0, height: 0, duration: 0, thumb: '' }]
      job.metrics = { size_mb: Number((DOWNLOAD_BYTES / 1_048_576).toFixed(1)) }
    }
    job.updated_at = now
  }
}

/** Advance every running run to the present; register the LoRA when done. */
export function tickTraining(state: MockState): void {
  const now = Date.now()
  for (const r of state.training.runs) {
    if (r.status !== 'running' || !r.started_at) continue
    const target = Math.min(r.total_steps, Math.floor((now - r.started_at) / STEP_MS) + (r.checkpoints.length ? Number(r.checkpoints[r.checkpoints.length - 1].match(/-(\d+)\.safetensors$/)?.[1] ?? 0) : 0))
    while (r.step < target) {
      r.step += 1
      r.loss_history.push(Number((0.6 * (1 - r.step / r.total_steps) + 0.05 + Math.sin(r.step / 7) * 0.02).toFixed(4)))
      if (r.config.sample_every && r.step % r.config.sample_every === 0) r.samples.push({ step: r.step, path: `samples/sample-${String(r.step).padStart(5, '0')}.png` })
      if (r.config.save_every && r.step % r.config.save_every === 0 && r.step < r.total_steps) r.checkpoints.push(`${r.name}-${String(r.step).padStart(6, '0')}.safetensors`)
    }
    r.phase = 'training'
    r.eta_seconds = ((r.total_steps - r.step) * STEP_MS) / 1000
    r.peak_vram_mb = Math.min(r.config.estimated_vram_mb, 8000 + r.step * 5)
    r.updated_at = now
    const job = trainingJob(state, r)
    if (job) {
      job.progress = Math.round((100 * r.step) / r.total_steps)
      job.phase = `training · step ${r.step}/${r.total_steps}`
      job.metrics = { loss_history: [...r.loss_history], final_loss: r.loss_history[r.loss_history.length - 1] ?? null, steps: r.step, peak_vram_mb: r.peak_vram_mb }
    }
    if (r.step >= r.total_steps) {
      r.status = 'complete'
      r.phase = 'complete'
      r.finished_at = now
      r.eta_seconds = null
      const entry: LoraEntry = {
        id: id('lora'),
        name: r.name,
        file: `C:/Users/you/AppData/Roaming/ltx-desktop/loras/${r.config.target}/${r.name.replace(/[^A-Za-z0-9_-]+/g, '-')}.safetensors`,
        target: r.config.target,
        base_model: r.config.target,
        trigger: r.trigger,
        dataset_id: r.dataset_id,
        run_id: r.id,
        job_id: r.job_id,
        preset: r.preset,
        default_multiplier: 1,
        size_bytes: 37_600_000,
        imported: false,
        created_at: now,
      }
      state.training.loras.unshift(entry)
      r.lora_id = entry.id
      r.lora_path = entry.file
      r.log_tail = 'steps: 100%|██████████| done\nsaved LoRA'
      if (job) {
        job.status = 'complete'
        job.progress = 100
        job.phase = 'complete'
        job.finished_at = now
        job.outputs = [{ path: entry.file, kind: 'file', width: 0, height: 0, duration: 0, thumb: '' }, ...r.samples.slice(-4).map(s => ({ path: s.path, kind: 'image' as const, width: 1024, height: 1024, duration: 0, thumb: s.path }))]
      }
    }
  }
}

export function registerTrainingRoutes(router: Router, store: Store): void {
  const status = (state: MockState): TrainingStatusResponse => ({
    trainers: TRAINERS,
    weights: { z_image: { dit: 'C:/models/z-image/dit.safetensors', vae: 'C:/models/z-image/vae.safetensors', text_encoder: 'C:/models/z-image/qwen3.safetensors' } },
    machine_vram_mb: MACHINE_VRAM_MB,
    active_run_id: state.training.runs.find(r => r.status === 'running' || r.status === 'queued')?.id ?? '',
  })

  router.get('/api/training/status', () => store.mutate(state => { tickTraining(state); return status(state) }))
  router.put('/api/training/weights/:target', req => ({ [req.params.target]: req.body }))

  router.get('/api/training/datasets', () => ({ datasets: store.data.training.datasets }))
  router.post('/api/training/datasets', req => store.mutate(state => {
    const d: Dataset = { id: id('ds'), name: String(req.body.name ?? ''), preset: (req.body.preset as DatasetPreset) ?? 'character', trigger: String(req.body.trigger ?? ''), items: [], caption_model: '', folder: '', created_at: Date.now(), updated_at: Date.now() }
    d.folder = `C:/Users/you/AppData/Roaming/ltx-desktop/training/datasets/${d.id}`
    state.training.datasets.unshift(d)
    return d
  }))
  router.get('/api/training/datasets/:id', req => dataset(store.data, req.params.id))
  router.put('/api/training/datasets/:id', req => store.mutate(state => {
    const d = dataset(state, req.params.id)
    if (typeof req.body.name === 'string') d.name = req.body.name
    if (typeof req.body.preset === 'string') d.preset = req.body.preset as DatasetPreset
    if (typeof req.body.trigger === 'string') d.trigger = req.body.trigger
    d.updated_at = Date.now()
    return d
  }))
  router.delete('/api/training/datasets/:id', req => store.mutate(state => {
    dataset(state, req.params.id)
    state.training.datasets = state.training.datasets.filter(d => d.id !== req.params.id)
    return { status: 'ok' }
  }))
  router.post('/api/training/datasets/:id/import', req => store.mutate(state => {
    const d = dataset(state, req.params.id)
    const before = d.items.length
    const folder = String(req.body.folder ?? '')
    if (folder) {
      if (!/^([A-Za-z]:[\\/]|\/)/.test(folder)) throw new MockHttpError(400, 'Folder must be an absolute path to an existing directory')
      for (let i = 1; i <= 6; i++) d.items.push(item(`${String(d.items.length + 1).padStart(4, '0')}-${folder.split(/[\\/]/).filter(Boolean).pop()}-${i}.png`, 'folder', ''))
    }
    for (const path of (req.body.image_paths as string[] | undefined) ?? []) d.items.push(item(`${String(d.items.length + 1).padStart(4, '0')}-${path.split(/[\\/]/).pop()}`, 'folder', ''))
    const video = String(req.body.video_path ?? '')
    if (video) {
      const fps = Number(req.body.video_fps ?? 1) || 1
      const max = Number(req.body.video_max_frames ?? 24) || 24
      for (let i = 0; i < Math.min(max, Math.round(8 * fps)); i++) d.items.push(item(`${String(d.items.length + 1).padStart(4, '0')}-${video.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '')}-${(i / fps).toFixed(2)}.jpg`, 'video', `${video}@${(i / fps).toFixed(2)}s`))
    }
    for (const jobId of (req.body.job_ids as string[] | undefined) ?? []) {
      const job = state.historyJobs.find(j => j.id === jobId)
      if (!job) throw new MockHttpError(404, `Job not found: ${jobId}`)
      for (const output of job.outputs.filter(o => o.kind === 'image')) d.items.push(item(`${String(d.items.length + 1).padStart(4, '0')}-${output.path.split('/').pop()}`, 'history', job.id))
    }
    const analysisId = String(req.body.analysis_id ?? '')
    if (analysisId) {
      const analysis = state.analyses[analysisId]
      if (!analysis) throw new MockHttpError(404, 'Video analysis not found')
      for (const shot of analysis.shots) for (const frame of shot.frames) d.items.push(item(`${String(d.items.length + 1).padStart(4, '0')}-${frame.path.split('/').pop()}`, 'analysis', analysisId))
    }
    if (d.items.length === before) throw new MockHttpError(400, 'Nothing importable was found (PNG, JPG or WebP images, or a readable video).')
    d.updated_at = Date.now()
    return d
  }))
  router.post('/api/training/datasets/:id/caption', req => store.mutate(state => {
    const d = dataset(state, req.params.id)
    for (const it of d.items) {
      if (it.edited && !req.body.overwrite_edited) continue
      it.caption = withTrigger(`A ${d.preset === 'object' ? 'small object' : 'person'} in soft light, ${it.file.replace(/\.[^.]+$/, '').replace(/^\d+-/, '').replace(/[-_]/g, ' ')}`, d.trigger, d.preset)
      it.edited = false
    }
    d.caption_model = 'Florence-2-large (UI mock)'
    d.updated_at = Date.now()
    return d
  }))
  router.put('/api/training/datasets/:id/items/:itemId', req => store.mutate(state => {
    const d = dataset(state, req.params.id)
    const it = d.items.find(i => i.id === req.params.itemId)
    if (!it) throw new MockHttpError(404, 'Item not found')
    it.caption = String(req.body.caption ?? '')
    it.edited = true
    return d
  }))
  router.delete('/api/training/datasets/:id/items/:itemId', req => store.mutate(state => {
    const d = dataset(state, req.params.id)
    d.items = d.items.filter(i => i.id !== req.params.itemId)
    return d
  }))
  router.get('/api/training/datasets/:id/media', req => {
    const d = dataset(store.data, req.params.id)
    const file = req.query.get('path') ?? ''
    const it = d.items.find(i => i.file === file)
    if (!it) throw new MockHttpError(400, 'File is not part of this dataset')
    return placeholderFrame(it.caption || it.file, it.source, `${d.id}/${file}`)
  })
  router.get('/api/training/runs/:id/media', req => {
    const r = run(store.data, req.params.id)
    const file = req.query.get('path') ?? ''
    return placeholderFrame(`${r.name} · ${file.split('/').pop()}`, 'sample', `${r.id}/${file}`)
  })

  router.post('/api/training/suggest', req => {
    const d = dataset(store.data, String(req.body.dataset_id ?? ''))
    return suggest(String(req.body.target ?? 'z_image'), d.preset, d.items.length)
  })

  router.get('/api/training/runs', () => store.mutate(state => { tickTraining(state); return { runs: state.training.runs } }))
  router.get('/api/training/runs/:id', req => store.mutate(state => { tickTraining(state); return run(state, req.params.id) }))
  router.post('/api/training/runs', req => store.mutate(state => {
    tickTraining(state)
    const d = dataset(state, String(req.body.dataset_id ?? ''))
    if (d.items.length < 4) throw new MockHttpError(400, 'A LoRA needs at least 4 captioned images (12 or more is the sweet spot).')
    const resumeId = String(req.body.resume_run_id ?? '')
    let config: TrainingConfig
    let resumeFrom = ''
    if (resumeId) {
      const previous = run(state, resumeId)
      if (previous.status === 'running' || previous.status === 'queued') throw new MockHttpError(409, 'That run is still active')
      if (!previous.checkpoints.length) throw new MockHttpError(400, 'That run left no checkpoint to resume from')
      resumeFrom = previous.checkpoints[previous.checkpoints.length - 1]
      config = { ...previous.config }
    } else {
      config = (req.body.config as TrainingConfig | null | undefined) ?? suggest('z_image', d.preset, d.items.length)
    }
    if (config.estimated_vram_mb > MACHINE_VRAM_MB) throw new MockHttpError(400, `${config.target} LoRA training is estimated at ${(config.estimated_vram_mb / 1024).toFixed(1)} GB; this machine has 12 GB. Pick an image target (Z-Image, Qwen-Image, FLUX) or train elsewhere.`)
    const trainer = TRAINERS.find(t => t.id === config.trainer)
    if (trainer && !trainer.installed) throw new MockHttpError(400, trainer.reason)
    if (state.training.runs.some(r => r.status === 'running' || r.status === 'queued')) throw new MockHttpError(409, 'A training run is already in progress')
    // Shorter runs in the mock so the loop is visible within a test.
    const total = Math.min(config.steps, 80)
    const now = Date.now()
    const r: TrainingRun = {
      id: id('run'),
      name: String(req.body.name ?? '').trim() || `${d.name} · ${config.target}`,
      dataset_id: d.id,
      preset: d.preset,
      trigger: d.trigger,
      config: { ...config, steps: total, save_every: Math.min(config.save_every, 20), sample_every: Math.min(config.sample_every || 20, 20) },
      status: 'running',
      phase: 'preparing',
      step: 0,
      total_steps: total,
      loss_history: [],
      eta_seconds: (total * STEP_MS) / 1000,
      samples: [],
      checkpoints: resumeFrom ? [resumeFrom] : [],
      lora_id: '',
      lora_path: '',
      job_id: '',
      error: '',
      log_tail: '',
      peak_vram_mb: null,
      started_at: now,
      finished_at: null,
      created_at: now,
      updated_at: now,
    }
    if (resumeFrom) r.step = Number(resumeFrom.match(/-(\d+)\.safetensors$/)?.[1] ?? 0)
    const job: Job = {
      id: `job_${r.id}`,
      kind: 'training',
      status: 'running',
      progress: 0,
      phase: 'preparing',
      title: r.name,
      created_at: now,
      updated_at: now,
      started_at: now,
      finished_at: null,
      model: config.target,
      provider: config.trainer,
      seed: config.seed,
      prompt: d.trigger,
      negative_prompt: '',
      spec: {},
      params: { ...config },
      inputs: { dataset_id: d.id, images: d.items.length, resume_from: resumeFrom, run_id: r.id },
      outputs: [],
      metrics: {},
      parent_job_id: '',
      project_id: '',
      shot_id: '',
      error: '',
    }
    r.job_id = job.id
    state.historyJobs.unshift(job)
    state.training.runs.unshift(r)
    return r
  }))
  router.post('/api/training/runs/:id/cancel', req => store.mutate(state => {
    tickTraining(state)
    const r = run(state, req.params.id)
    if (r.status === 'running' || r.status === 'queued') {
      r.status = 'cancelled'
      r.phase = 'cancelled'
      r.error = 'Cancelled'
      r.finished_at = Date.now()
      r.eta_seconds = null
      const job = trainingJob(state, r)
      if (job) { job.status = 'cancelled'; job.phase = 'cancelled'; job.error = 'Cancelled'; job.finished_at = Date.now() }
    }
    return r
  }))
  router.delete('/api/training/runs/:id', req => store.mutate(state => {
    const r = run(state, req.params.id)
    if (r.status === 'running' || r.status === 'queued') throw new MockHttpError(409, 'Cancel the run before deleting it')
    state.training.runs = state.training.runs.filter(x => x.id !== r.id)
    return { status: 'ok' }
  }))

  router.get('/api/training/loras', req => {
    const model = (req.query.get('model') ?? '').toLowerCase().replace(/[_-]/g, '')
    const target = req.query.get('target') ?? ''
    let list = store.data.training.loras
    if (model) {
      const found = ['qwen_image', 'z_image', 'wan22', 'flux', 'ltx2'].find(t => model.includes(t.replace('_', ''))) ?? (model.includes('wan') ? 'wan22' : model.includes('ltx') ? 'ltx2' : '')
      list = found ? list.filter(l => l.target === found) : []
    } else if (target) list = list.filter(l => l.target === target)
    return { loras: list }
  })
  router.post('/api/training/loras/import', req => store.mutate(state => {
    const path = String(req.body.path ?? '')
    if (!path.toLowerCase().endsWith('.safetensors')) throw new MockHttpError(400, 'A LoRA is a .safetensors file')
    const target = String(req.body.target ?? 'z_image')
    if (!(target in BASE)) throw new MockHttpError(400, `Unknown target ${target}`)
    const name = String(req.body.name ?? '') || path.split(/[\\/]/).pop()!.replace(/\.safetensors$/i, '')
    const entry: LoraEntry = { id: id('lora'), name, file: `C:/Users/you/AppData/Roaming/ltx-desktop/loras/${target}/${name}.safetensors`, target, base_model: target, trigger: String(req.body.trigger ?? ''), dataset_id: '', run_id: '', job_id: '', preset: 'character', default_multiplier: 1, size_bytes: 21_000_000, imported: true, created_at: Date.now() }
    state.training.loras.unshift(entry)
    return entry
  }))
  router.post('/api/training/loras/download', req => store.mutate(state => {
    const target = String(req.body.target ?? 'z_image')
    if (!(target in BASE)) throw new MockHttpError(400, `Unknown target ${target}`)
    const source = parseLoraLink(String(req.body.url ?? ''))
    const now = Date.now()
    // The api_key in the request is used for the fetch and stored nowhere.
    const job: Job = {
      id: id('job_lora-dl'),
      kind: 'download',
      status: 'running',
      progress: 0,
      phase: 'resolving',
      title: `LoRA · ${source.filename}`,
      created_at: now,
      updated_at: now,
      started_at: now,
      finished_at: null,
      model: target,
      provider: source.provider,
      seed: null,
      prompt: '',
      negative_prompt: '',
      spec: {},
      params: { target, name: String(req.body.name ?? ''), trigger: String(req.body.trigger ?? ''), filename: source.filename },
      inputs: { lora_url: String(req.body.url ?? '').trim() },
      outputs: [],
      metrics: {},
      parent_job_id: '',
      project_id: '',
      shot_id: '',
      error: '',
    }
    state.historyJobs.unshift(job)
    return { job_id: job.id }
  }))
  router.put('/api/training/loras/:id', req => store.mutate(state => {
    const entry = state.training.loras.find(l => l.id === req.params.id)
    if (!entry) throw new MockHttpError(404, 'LoRA not found')
    if (typeof req.body.name === 'string' && req.body.name.trim()) entry.name = req.body.name.trim()
    if (typeof req.body.trigger === 'string') entry.trigger = req.body.trigger
    if (typeof req.body.default_multiplier === 'number') entry.default_multiplier = req.body.default_multiplier
    return entry
  }))
  router.delete('/api/training/loras/:id', req => store.mutate(state => {
    state.training.loras = state.training.loras.filter(l => l.id !== req.params.id)
    return { status: 'ok' }
  }))
}

/** A trained LoRA so the pickers have something to offer from the first launch. */
export function seedTraining(): MockState['training'] {
  const now = Date.now() - 86_400_000
  const lora: LoraEntry = { id: 'lora-seed-mara', name: 'Mara v1', file: 'C:/Users/you/AppData/Roaming/ltx-desktop/loras/z_image/mara-v1.safetensors', target: 'z_image', base_model: 'z_image', trigger: 'mara_v1', dataset_id: 'ds-seed-mara', run_id: 'run-seed-mara', job_id: 'job_training-1', preset: 'character', default_multiplier: 0.9, size_bytes: 37_600_000, imported: false, created_at: now }
  const items: DatasetItem[] = Array.from({ length: 8 }, (_, i) => ({ id: `item-seed-${i + 1}`, file: `${String(i + 1).padStart(4, '0')}-mara-${i + 1}.png`, caption: `mara_v1, a woman with short dark hair in a green field jacket, ${['front view', 'three-quarter view', 'profile', 'looking down', 'smiling', 'at the console', 'walking', 'back view'][i]}`, edited: i === 0, source: i < 6 ? 'folder' : 'history', origin: i < 6 ? '' : 'job_image_gen-1', width: 1024, height: 1024 }))
  const dataset: Dataset = { id: 'ds-seed-mara', name: 'Mara references', preset: 'character', trigger: 'mara_v1', items, caption_model: 'Florence-2-large (UI mock)', folder: 'C:/Users/you/AppData/Roaming/ltx-desktop/training/datasets/ds-seed-mara', created_at: now, updated_at: now }
  const steps = 600
  const config = suggest('z_image', 'character', items.length)
  const run: TrainingRun = {
    id: 'run-seed-mara', name: 'Mara v1', dataset_id: dataset.id, preset: 'character', trigger: 'mara_v1', config: { ...config, steps }, status: 'complete', phase: 'complete', step: steps, total_steps: steps,
    loss_history: Array.from({ length: 60 }, (_, i) => Number((0.6 * (1 - i / 60) + 0.05 + Math.sin(i / 5) * 0.02).toFixed(4))),
    eta_seconds: null, samples: [100, 200, 300, 400, 500, 600].map(step => ({ step, path: `samples/sample-${String(step).padStart(5, '0')}.png` })), checkpoints: ['Mara-v1-000100.safetensors', 'Mara-v1-000200.safetensors', 'Mara-v1-000300.safetensors', 'Mara-v1-000400.safetensors', 'Mara-v1-000500.safetensors'],
    lora_id: lora.id, lora_path: lora.file, job_id: 'job_training-1', error: '', log_tail: 'steps: 100%|██████████| 600/600 [12:40<00:00, avr_loss=0.071]\nsaved LoRA', peak_vram_mb: 10850, started_at: now, finished_at: now + 760_000, created_at: now, updated_at: now + 760_000,
  }
  return { datasets: [dataset], runs: [run], loras: [lora] }
}
