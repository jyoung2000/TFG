/** The Model Library: one catalog over local weights and hosted providers. */

export type LibraryTask = 'video' | 'image' | 'text'
export type LibrarySourceKind = 'local' | 'hosted'

/** Providers that generate images/video. `local` is the only offline one. */
export type MediaProviderId = 'local' | 'fal' | 'wavespeed' | 'replicate'

/** Providers that run the AI Director's text model. */
export type TextProviderId = 'openrouter' | 'anthropic' | 'xai' | 'gemini' | 'openai_compatible'

export interface LibraryModel {
  id: string
  name: string
  /** wangp | native | ollama | openai_compatible | openrouter | anthropic | xai | gemini | fal | wavespeed | replicate */
  provider: string
  source: LibrarySourceKind
  task: LibraryTask
  description: string
  /** installed | available | downloading | active | incompatible | needs_key | example */
  state: string
  installed: boolean
  downloadable: boolean
  size_gb: number | null
  estimated_min_vram_gb: number | null
  fits_gpu: boolean | null
  supports_image_input: boolean
  context_length: number | null
  family: string
  quantization: string
  /** True for example ids this app ships for providers without a catalog API. */
  curated: boolean
  url: string
}

export interface LibrarySourceStatus {
  id: string
  label: string
  kind: LibrarySourceKind
  configured: boolean
  count: number
  error: string
  catalog_url: string
}

export interface ModelSearchResponse {
  models: LibraryModel[]
  total: number
  sources: LibrarySourceStatus[]
  gpu_name: string | null
  gpu_vram_gb: number | null
  models_path: string
  offline_ready: boolean
  offline_note: string
}

export interface LibraryDownloadStatus {
  active: boolean
  provider: string
  model_id: string
  status: 'idle' | 'running' | 'complete' | 'failed' | 'cancelled'
  files_total: number
  files_done: number
  downloaded_bytes: number
  total_bytes: number
  progress: number
  error: string
  message: string
}

export const MEDIA_PROVIDER_LABELS: Record<MediaProviderId, string> = {
  local: 'This computer (offline)',
  fal: 'fal.ai',
  wavespeed: 'WaveSpeed AI',
  replicate: 'Replicate',
}

export const TEXT_PROVIDER_LABELS: Record<TextProviderId, string> = {
  openrouter: 'OpenRouter',
  anthropic: 'Claude (Anthropic)',
  xai: 'Grok (xAI)',
  gemini: 'Gemini (Google)',
  openai_compatible: 'Local / OpenAI-compatible',
}

/** Where each provider publishes the model ids it accepts. */
export const PROVIDER_DOC_URLS: Record<string, string> = {
  fal: 'https://fal.ai/models',
  wavespeed: 'https://wavespeed.ai/models',
  replicate: 'https://replicate.com/explore',
  openrouter: 'https://openrouter.ai/models',
  anthropic: 'https://docs.anthropic.com/en/docs/about-claude/models',
  xai: 'https://docs.x.ai/docs/models',
  gemini: 'https://ai.google.dev/gemini-api/docs/models',
  ollama: 'https://ollama.com/library',
}

export const LIBRARY_STATE_META: Record<string, { label: string; className: string }> = {
  active: { label: 'In use', className: 'bg-violet-900/60 text-violet-200' },
  installed: { label: 'Installed', className: 'bg-emerald-900/60 text-emerald-300' },
  available: { label: 'Available', className: 'bg-zinc-800 text-zinc-300' },
  downloading: { label: 'Downloading', className: 'bg-sky-900/60 text-sky-300' },
  example: { label: 'Example id', className: 'bg-amber-950/70 text-amber-300' },
  needs_key: { label: 'Needs API key', className: 'bg-zinc-800 text-zinc-500' },
  incompatible: { label: 'Too big for this GPU', className: 'bg-red-950/70 text-red-300' },
}
