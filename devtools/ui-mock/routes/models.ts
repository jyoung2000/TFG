/**
 * Host model status/downloads, film capabilities, and the Model Library.
 *
 * The machine is described as a plausible mid-range workstation (an RTX 4070)
 * so the GPU verdicts, "fits this GPU" badges and quality-profile
 * recommendations all have something real to say. Downloads are simulated and
 * complete on their own; nothing is fetched.
 */

import type { FilmCapabilities, FilmModelCapability, FilmQualityProfile } from '../../../frontend/types/film'
import type {
  LibraryModel,
  LibrarySourceStatus,
  ModelSearchResponse,
  ProviderTestResult,
} from '../../../frontend/types/models'
import { MockHttpError, type Router } from '../http'
import { EMPTY_LIBRARY_DOWNLOAD, type MockState, type Store } from '../state'

const GPU_NAME = 'NVIDIA GeForce RTX 4070'
const GPU_VRAM = 12
const MODELS_PATH = '/home/you/TFG/Wan2GP/ckpts'

interface HostModel {
  id: string
  name: string
  description: string
  sizeGb: number
  required: boolean
}

const HOST_MODELS: HostModel[] = [
  { id: 'checkpoint', name: 'LTX-2 checkpoint', description: 'Main video diffusion weights', sizeGb: 18.4, required: true },
  { id: 'text_encoder', name: 'Text encoder', description: 'Prompt encoder (optional with cloud encoding)', sizeGb: 9.2, required: false },
  { id: 'upsampler', name: 'Latent upsampler', description: 'Detail pass for final renders', sizeGb: 2.1, required: false },
  { id: 'zit', name: 'Z Image Turbo', description: 'Text-to-image model', sizeGb: 6.6, required: false },
]

const GB = 1024 ** 3

function isDownloaded(state: MockState, id: string): boolean {
  return state.downloadedModels.includes(id)
}

function profiles(): FilmQualityProfile[] {
  return [
    {
      id: 'fast_preview',
      label: 'Fast Preview',
      model: 'fast',
      resolution: '960x540',
      description: 'Quickest look at the shot',
      recommended: false,
      fits_gpu: true,
    },
    {
      id: 'balanced',
      label: 'Balanced',
      model: 'fast',
      resolution: '1280x720',
      description: 'Everyday quality for 8-16 GB cards',
      recommended: true,
      fits_gpu: true,
    },
    {
      id: 'quality',
      label: 'Quality',
      model: 'pro',
      resolution: '1920x1080',
      description: 'Best output; wants 16 GB or more',
      recommended: false,
      fits_gpu: false,
    },
    {
      id: 'custom',
      label: 'Custom',
      model: '',
      resolution: '',
      description: "Use the shot's own model and resolution",
      recommended: false,
      fits_gpu: null,
    },
  ]
}

function capabilities(state: MockState): FilmCapabilities {
  const models: FilmModelCapability[] = HOST_MODELS.map(model => {
    const downloaded = isDownloaded(state, model.id)
    const vram = model.id === 'checkpoint' ? 10 : model.id === 'zit' ? 8 : 4
    return {
      id: model.id,
      label: model.name,
      modes: model.id === 'zit' ? ['t2i'] : ['t2v', 'i2v'],
      supports_image_to_video: model.id !== 'zit',
      supports_text_to_video: model.id !== 'zit',
      supports_reference_images: model.id !== 'zit',
      supports_audio: false,
      downloaded,
      download_state: downloaded ? 'downloaded' : 'not_downloaded',
      execution: 'wangp',
      required: model.required,
      disk_size_gb: model.sizeGb,
      estimated_min_vram_gb: vram,
      fits_gpu: vram <= GPU_VRAM,
      supported_resolutions: model.id === 'zit' ? ['1024x1024'] : ['960x540', '1280x720', '1920x1080'],
      family: model.id === 'zit' ? 'z-image' : 'ltx-2',
      task: model.id === 'zit' ? 'image' : 'video',
      description: model.description,
      quantization: 'bf16',
      state: downloaded ? (model.id === 'checkpoint' ? 'active' : 'installed') : 'available',
      installed_size_gb: downloaded ? model.sizeGb : null,
      is_active: model.id === 'checkpoint' && downloaded,
      vram_is_estimate: true,
    }
  })

  const missing = models.filter(m => m.required && !m.downloaded).reduce((total, m) => total + (m.disk_size_gb ?? 0), 0)

  return {
    gpu_name: GPU_NAME,
    gpu_vram_gb: GPU_VRAM,
    execution_mode: 'wangp',
    gpu_verdict: `${GPU_NAME} (${GPU_VRAM} GB) runs the balanced profile comfortably; 1080p finals may not fit.`,
    gpu_verdict_level: 'partial',
    models,
    total_required_download_gb: missing > 0 ? Math.round(missing * 10) / 10 : null,
    text_encoder_optional: true,
    vram_note: 'VRAM figures are estimates from this repository’s documented measurements, not a live probe.',
    profiles: profiles(),
    models_path: MODELS_PATH,
    system_ram_gb: 32,
    cuda_available: true,
  }
}

// ---- Model Library ----

const LOCAL_LIBRARY: LibraryModel[] = [
  libraryModel('wangp', 'ltx2_22B_distilled', 'LTX-2 22B (distilled)', 'video', {
    description: 'The default local video model in the WanGP checkout.',
    size_gb: 18.4,
    estimated_min_vram_gb: 10,
    family: 'ltx-2',
    quantization: 'bf16',
  }),
  libraryModel('wangp', 'ltx2_22B_full', 'LTX-2 22B (full)', 'video', {
    description: 'Higher quality, needs considerably more VRAM.',
    size_gb: 44.2,
    estimated_min_vram_gb: 24,
    family: 'ltx-2',
    quantization: 'bf16',
  }),
  libraryModel('wangp', 'flux_dev', 'FLUX.1 dev', 'image', {
    description: 'Text-to-image, good for reference frames.',
    size_gb: 23.8,
    estimated_min_vram_gb: 12,
    family: 'flux',
  }),
  libraryModel('wangp', 'flux_schnell', 'FLUX.1 schnell', 'image', {
    description: 'Fast, few-step text-to-image.',
    size_gb: 23.8,
    estimated_min_vram_gb: 12,
    family: 'flux',
  }),
  libraryModel('native', 'ltx-pipeline', 'LTX pipeline weights', 'video', {
    description: 'The native (non-WanGP) pipeline. Download it from Installed & GPU.',
    size_gb: 29.7,
    estimated_min_vram_gb: 32,
    family: 'ltx-2',
  }),
  libraryModel('ollama', 'llama3.1:8b', 'Llama 3.1 8B', 'text', {
    description: 'Local text model — enough for a fully offline AI Director.',
    size_gb: 4.7,
    context_length: 131072,
    family: 'llama',
    quantization: 'Q4_K_M',
  }),
  libraryModel('ollama', 'qwen2.5:14b', 'Qwen 2.5 14B', 'text', {
    description: 'Stronger local director; wants more RAM.',
    size_gb: 9.0,
    context_length: 131072,
    family: 'qwen',
    quantization: 'Q4_K_M',
  }),
]

const HOSTED_LIBRARY: LibraryModel[] = [
  libraryModel('fal', 'fal-ai/ltx-video-13b-distilled', 'LTX Video 13B (distilled)', 'video', {
    description: 'Example id — check fal’s catalog for the current list.',
    curated: true,
    supports_image_input: true,
  }),
  libraryModel('fal', 'fal-ai/flux/schnell', 'FLUX.1 schnell', 'image', { description: 'Example id.', curated: true }),
  libraryModel('wavespeed', 'wavespeed-ai/wan-2.2/t2v-720p', 'Wan 2.2 T2V 720p', 'video', {
    description: 'Example id — check WaveSpeed’s catalog.',
    curated: true,
  }),
  libraryModel('wavespeed', 'wavespeed-ai/flux-dev', 'FLUX.1 dev', 'image', { description: 'Example id.', curated: true }),
  libraryModel('replicate', 'lightricks/ltx-video', 'LTX Video', 'video', {
    description: 'Discovered from Replicate collections in the full app.',
    supports_image_input: true,
  }),
  libraryModel('replicate', 'black-forest-labs/flux-schnell', 'FLUX.1 schnell', 'image', { description: '' }),
]

const TEXT_HOSTED: Record<string, string[]> = {
  openrouter: ['openai/gpt-4o-mini', 'anthropic/claude-sonnet-5', 'google/gemini-2.0-flash'],
  anthropic: ['claude-sonnet-5', 'claude-opus-5'],
  xai: ['grok-4'],
  gemini: ['gemini-2.0-flash'],
}

function libraryModel(
  provider: string,
  id: string,
  name: string,
  task: LibraryModel['task'],
  extra: Partial<LibraryModel> = {},
): LibraryModel {
  const local = ['wangp', 'native', 'ollama', 'openai_compatible'].includes(provider)
  return {
    id,
    name,
    provider,
    source: local ? 'local' : 'hosted',
    task,
    description: '',
    state: 'available',
    installed: false,
    downloadable: provider === 'wangp' || provider === 'ollama',
    size_gb: null,
    estimated_min_vram_gb: null,
    fits_gpu: null,
    supports_image_input: false,
    context_length: null,
    family: '',
    quantization: '',
    curated: false,
    url: '',
    ...extra,
  }
}

const CATALOG_URLS: Record<string, string> = {
  fal: 'https://fal.ai/models',
  wavespeed: 'https://wavespeed.ai/models',
  replicate: 'https://replicate.com/explore',
}

const SOURCE_LABELS: Record<string, string> = {
  wangp: 'Local · WanGP models',
  native: 'Local · LTX pipeline',
  ollama: 'Local · Ollama',
  openai_compatible: 'Local · OpenAI-compatible server',
  openrouter: 'OpenRouter',
  anthropic: 'Claude (Anthropic)',
  xai: 'Grok (xAI)',
  gemini: 'Gemini (Google)',
  fal: 'fal.ai',
  wavespeed: 'WaveSpeed AI',
  replicate: 'Replicate',
}

function providerConfigured(state: MockState, provider: string): boolean {
  const s = state.settings
  switch (provider) {
    case 'openrouter':
      return s.hasOpenrouterApiKey
    case 'anthropic':
      return s.hasAnthropicApiKey
    case 'xai':
      return s.hasXaiApiKey
    case 'gemini':
      return s.hasGeminiApiKey
    case 'fal':
      return s.hasFalApiKey
    case 'wavespeed':
      return s.hasWavespeedApiKey
    case 'replicate':
      return s.hasReplicateApiKey
    case 'openai_compatible':
      return Boolean(s.openaiCompatibleBaseUrl.trim())
    default:
      return true
  }
}

function libraryFor(state: MockState): LibraryModel[] {
  const models: LibraryModel[] = []

  for (const model of LOCAL_LIBRARY) {
    const installed =
      (model.provider === 'wangp' && model.id === 'ltx2_22B_distilled' && isDownloaded(state, 'checkpoint')) ||
      (model.provider === 'ollama' && state.rememberedModels.some(m => m.model_id === model.id))
    const fits = model.estimated_min_vram_gb == null ? null : model.estimated_min_vram_gb <= GPU_VRAM
    models.push({
      ...model,
      installed,
      fits_gpu: fits,
      state:
        state.libraryDownload.active && state.libraryDownload.model_id === model.id
          ? 'downloading'
          : installed
            ? model.id === 'ltx2_22B_distilled'
              ? 'active'
              : 'installed'
            : fits === false
              ? 'incompatible'
              : 'available',
    })
  }

  for (const model of HOSTED_LIBRARY) {
    const configured = providerConfigured(state, model.provider)
    models.push({
      ...model,
      // What the user needs to see first is whether they can use it at all;
      // the "example id" nuance only matters once a key exists.
      state: !configured ? 'needs_key' : model.curated ? 'example' : 'available',
      url: CATALOG_URLS[model.provider] ?? '',
    })
  }

  for (const [provider, ids] of Object.entries(TEXT_HOSTED)) {
    if (!providerConfigured(state, provider)) continue
    for (const id of ids) {
      models.push(
        libraryModel(provider, id, id, 'text', { state: 'available', context_length: 128000, source: 'hosted' }),
      )
    }
  }

  for (const remembered of state.rememberedModels) {
    if (models.some(m => m.id === remembered.model_id && m.provider === remembered.provider)) continue
    models.push(
      libraryModel(remembered.provider, remembered.model_id, remembered.model_id, 'video', {
        description: 'Added by you.',
        state: providerConfigured(state, remembered.provider) ? 'available' : 'needs_key',
      }),
    )
  }

  return models
}

function sources(state: MockState, models: LibraryModel[]): LibrarySourceStatus[] {
  const ids = ['wangp', 'native', 'ollama', 'openai_compatible', 'openrouter', 'anthropic', 'xai', 'gemini', 'fal', 'wavespeed', 'replicate']
  return ids.map(id => ({
    id,
    label: SOURCE_LABELS[id] ?? id,
    kind: ['wangp', 'native', 'ollama', 'openai_compatible'].includes(id) ? 'local' : 'hosted',
    configured: providerConfigured(state, id),
    count: models.filter(m => m.provider === id).length,
    error:
      id === 'openai_compatible' && !state.settings.openaiCompatibleBaseUrl.trim()
        ? ''
        : id === 'ollama' && !state.settings.openaiCompatibleBaseUrl.trim()
          ? ''
          : '',
    catalog_url: CATALOG_URLS[id] ?? '',
  }))
}

export function registerModelRoutes(router: Router, store: Store): void {
  // ---- Host models ----

  router.get('/health', () => {
    const state = store.data
    return {
      status: 'ok',
      models_loaded: isDownloaded(state, 'checkpoint'),
      active_model: isDownloaded(state, 'checkpoint') ? 'checkpoint' : null,
      gpu_info: { name: GPU_NAME, vram: GPU_VRAM, vramUsed: 2 },
      sage_attention: false,
      models_status: HOST_MODELS.map(model => ({
        name: model.id,
        downloaded: isDownloaded(state, model.id),
      })),
    }
  })

  router.get('/api/models', () => ({
    models: HOST_MODELS.map(model => ({
      id: model.id,
      name: model.name,
      size: Math.round(model.sizeGb * GB),
      downloaded: isDownloaded(store.data, model.id),
      downloadProgress: store.data.modelDownloads[model.id]?.progress ?? 0,
    })),
  }))

  router.get('/api/models/status', () => {
    const state = store.data
    const models = HOST_MODELS.map(model => ({
      name: model.id,
      description: model.description,
      downloaded: isDownloaded(state, model.id),
      size: isDownloaded(state, model.id) ? Math.round(model.sizeGb * GB) : 0,
      expected_size: Math.round(model.sizeGb * GB),
      required: model.required,
      is_folder: true,
    }))
    const total = models.reduce((sum, m) => sum + m.expected_size, 0)
    const downloaded = models.reduce((sum, m) => sum + m.size, 0)
    const encoder = HOST_MODELS.find(m => m.id === 'text_encoder')!
    return {
      models,
      all_downloaded: models.filter(m => m.required).every(m => m.downloaded),
      total_size: total,
      downloaded_size: downloaded,
      total_size_gb: Math.round((total / GB) * 10) / 10,
      downloaded_size_gb: Math.round((downloaded / GB) * 10) / 10,
      text_encoder_status: {
        name: encoder.name,
        downloaded: isDownloaded(state, 'text_encoder'),
        size: isDownloaded(state, 'text_encoder') ? Math.round(encoder.sizeGb * GB) : 0,
        expected_size: Math.round(encoder.sizeGb * GB),
      },
    }
  })

  const startHostDownload = (id: string) =>
    store.mutate(state => {
      if (isDownloaded(state, id)) return { status: 'already_downloaded' }
      state.modelDownloads[id] = { progress: 0, downloaded: false }
      // A simulated download that finishes on its own, so progress UI runs.
      const finishAt = Date.now() + 6000
      const tick = setInterval(() => {
        const remaining = finishAt - Date.now()
        store.mutate(inner => {
          const entry = inner.modelDownloads[id]
          if (!entry) return
          entry.progress = Math.min(100, Math.round(((6000 - Math.max(remaining, 0)) / 6000) * 100))
          if (remaining <= 0) {
            entry.progress = 100
            entry.downloaded = true
            if (!inner.downloadedModels.includes(id)) inner.downloadedModels.push(id)
            clearInterval(tick)
          }
        })
      }, 400)
      tick.unref?.()
      return { status: 'started' }
    })

  router.post('/api/models/download', req => startHostDownload(String(req.body.model_id ?? 'checkpoint')))
  router.post('/api/models/:modelId/download', req => startHostDownload(req.params.modelId))
  router.post('/api/text-encoder/download', () => startHostDownload('text_encoder'))

  router.get('/api/models/download/progress', () => {
    const entries = Object.entries(store.data.modelDownloads)
    const active = entries.find(([, value]) => !value.downloaded)
    const [id, value] = active ?? entries[entries.length - 1] ?? ['', { progress: 0, downloaded: true }]
    const model = HOST_MODELS.find(m => m.id === id)
    const totalBytes = model ? Math.round(model.sizeGb * GB) : 0
    return {
      status: active ? 'downloading' : entries.length ? 'complete' : 'idle',
      currentFile: model ? `${model.id}/weights.safetensors` : '',
      currentFileProgress: value.progress,
      totalProgress: value.progress,
      downloadedBytes: Math.round((totalBytes * value.progress) / 100),
      totalBytes,
      filesCompleted: value.downloaded ? 1 : 0,
      totalFiles: 1,
      error: null,
      speedMbps: active ? 118.4 : 0,
    }
  })

  router.delete('/api/models/:modelType', req =>
    store.mutate(state => {
      if (state.queue.active) throw new MockHttpError(409, 'Cannot remove a model while a render is running')
      const model = HOST_MODELS.find(m => m.id === req.params.modelType)
      if (!model) throw new MockHttpError(404, `Unknown model: ${req.params.modelType}`)
      state.downloadedModels = state.downloadedModels.filter(id => id !== model.id)
      delete state.modelDownloads[model.id]
      return { name: model.name, downloaded: false }
    }),
  )

  router.get('/api/film/capabilities', () => capabilities(store.data))

  // ---- Model Library ----

  router.get('/api/models/library', req => {
    const state = store.data
    const query = (req.query.get('query') ?? '').trim().toLowerCase()
    const task = req.query.get('task') ?? 'all'
    const source = req.query.get('source') ?? 'all'
    const onlyCompatible = req.query.get('only_compatible') === 'true'
    const limit = Number(req.query.get('limit') ?? 200) || 200

    const all = libraryFor(state)
    const filtered = all.filter(model => {
      if (task !== 'all' && model.task !== task) return false
      if (source !== 'all' && model.source !== source) return false
      if (onlyCompatible && model.fits_gpu === false) return false
      if (query && !`${model.id} ${model.name} ${model.description} ${model.family}`.toLowerCase().includes(query)) {
        return false
      }
      return true
    })

    const localVideo = all.some(m => m.source === 'local' && m.task !== 'text' && m.installed)
    const localText = all.some(m => m.source === 'local' && m.task === 'text' && m.installed)
    const response: ModelSearchResponse = {
      models: filtered.slice(0, limit),
      total: filtered.length,
      sources: sources(state, all),
      gpu_name: GPU_NAME,
      gpu_vram_gb: GPU_VRAM,
      models_path: MODELS_PATH,
      offline_ready: localVideo && localText,
      offline_note:
        localVideo && localText
          ? 'This machine can make a film with no network at all.'
          : `Still needed for a fully offline film: ${[!localVideo && 'a local video or image model', !localText && 'a local text model'].filter(Boolean).join(' and ')}.`,
    }
    return response
  })

  router.post('/api/models/library/download', req =>
    store.mutate(state => {
      const provider = String(req.body.provider ?? '')
      const modelId = String(req.body.model_id ?? '')
      if (!['wangp', 'ollama'].includes(provider)) {
        throw new MockHttpError(
          400,
          `${provider} models run on the provider's own hardware — there is nothing to download. Add the API key instead.`,
        )
      }
      const model = LOCAL_LIBRARY.find(m => m.id === modelId)
      const totalBytes = Math.round((model?.size_gb ?? 4) * GB)
      state.libraryDownload = {
        ...EMPTY_LIBRARY_DOWNLOAD,
        active: true,
        provider,
        model_id: modelId,
        status: 'running',
        files_total: 3,
        total_bytes: totalBytes,
        message: `Downloading ${modelId}`,
      }
      const startedAt = Date.now()
      const duration = 8000
      const tick = setInterval(() => {
        store.mutate(inner => {
          const download = inner.libraryDownload
          if (!download.active || download.model_id !== modelId) {
            clearInterval(tick)
            return
          }
          const ratio = Math.min(1, (Date.now() - startedAt) / duration)
          download.progress = Math.round(ratio * 100)
          download.files_done = Math.min(3, Math.floor(ratio * 3))
          download.downloaded_bytes = Math.round(totalBytes * ratio)
          if (ratio >= 1) {
            download.active = false
            download.status = 'complete'
            download.files_done = 3
            download.message = `${modelId} installed`
            if (provider === 'ollama') inner.rememberedModels.push({ provider, model_id: modelId })
            if (provider === 'wangp' && !inner.downloadedModels.includes('checkpoint')) {
              inner.downloadedModels.push('checkpoint')
            }
            clearInterval(tick)
          }
        })
      }, 400)
      tick.unref?.()
      return state.libraryDownload
    }),
  )

  router.get('/api/models/library/download', () => store.data.libraryDownload)

  router.post('/api/models/library/download/cancel', () =>
    store.mutate(state => {
      state.libraryDownload = { ...EMPTY_LIBRARY_DOWNLOAD, status: 'cancelled', message: 'Download cancelled' }
      return state.libraryDownload
    }),
  )

  // Same three-state answer the real backend gives: it worked, it failed, or
  // this provider publishes no free way to check a key.
  router.post('/api/models/library/providers/:provider/test', req => {
    const provider = req.params.provider
    const testable = ['openrouter', 'anthropic', 'xai', 'gemini', 'openai_compatible', 'fal', 'wavespeed', 'replicate']
    if (!testable.includes(provider)) throw new MockHttpError(400, `Unknown provider: ${provider}`)

    const state = store.data
    const label = SOURCE_LABELS[provider] ?? provider
    const configured = providerConfigured(state, provider)
    const result: ProviderTestResult = {
      provider,
      label,
      configured,
      ok: false,
      checked: false,
      message: '',
      models_found: 0,
    }
    if (!configured) {
      result.message =
        provider === 'openai_compatible' ? 'No endpoint set yet — add the base URL below.' : 'No API key saved yet.'
      return result
    }
    if (provider === 'fal' || provider === 'wavespeed') {
      result.message = `Key saved. ${label} publishes no free endpoint to check it against, so it is verified on your first render.`
      return result
    }
    result.checked = true
    result.ok = true
    if (provider === 'replicate') {
      result.message = 'Connected. The key is valid.'
      return result
    }
    const count = (TEXT_HOSTED[provider] ?? ['llama3.1:8b', 'qwen2.5:14b']).length
    result.models_found = count
    result.message = `Connected. ${count} model${count === 1 ? '' : 's'} available.`
    return result
  })

  router.post('/api/models/library/remember', req =>
    store.mutate(state => {
      const provider = String(req.body.provider ?? '')
      const modelId = String(req.body.model_id ?? '').trim()
      if (!modelId) throw new MockHttpError(400, 'A model id is required')
      if (!state.rememberedModels.some(m => m.provider === provider && m.model_id === modelId)) {
        state.rememberedModels.push({ provider, model_id: modelId })
      }
      if (!state.settings.recentModelIds.includes(modelId)) {
        state.settings.recentModelIds = [modelId, ...state.settings.recentModelIds].slice(0, 12)
      }
      return { status: 'ok' }
    }),
  )
}
