/**
 * LoRA training (phase 7). Mirrors `backend/film/training_models.py` and
 * `backend/film/training_api_types.py` — snake_case, no mapping layer.
 */

export type DatasetPreset = 'character' | 'style' | 'object'
export type TrainingStatus = 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'
export type ItemSource = 'folder' | 'video' | 'history' | 'analysis' | 'candidate'

/** Targets a LoRA can be trained for and the base models they apply to. */
export const LORA_TARGETS: { id: string; label: string; video: boolean }[] = [
  { id: 'z_image', label: 'Z-Image', video: false },
  { id: 'qwen_image', label: 'Qwen-Image', video: false },
  { id: 'flux', label: 'FLUX', video: false },
  { id: 'wan22', label: 'Wan 2.2 (video · 24 GB)', video: true },
  { id: 'ltx2', label: 'LTX-2 (video · 32 GB+)', video: true },
]

export const PRESET_LABEL: Record<DatasetPreset, string> = { character: 'Character', style: 'Style', object: 'Object' }

export interface DatasetItem {
  id: string
  file: string
  caption: string
  edited: boolean
  source: ItemSource
  origin: string
  width: number
  height: number
}

export interface Dataset {
  id: string
  name: string
  preset: DatasetPreset
  trigger: string
  items: DatasetItem[]
  caption_model: string
  folder: string
  created_at: number
  updated_at: number
}

export interface TrainingConfig {
  target: string
  trainer: string
  rank: number
  steps: number
  learning_rate: number
  batch_size: number
  resolution: number
  buckets: number[]
  blocks_to_swap: number
  fp8: boolean
  save_every: number
  sample_every: number
  seed: number
  estimated_vram_mb: number
}

export interface TrainingSample {
  step: number
  path: string
}

export interface TrainingRun {
  id: string
  name: string
  dataset_id: string
  preset: DatasetPreset
  trigger: string
  config: TrainingConfig
  status: TrainingStatus
  phase: string
  step: number
  total_steps: number
  loss_history: number[]
  eta_seconds: number | null
  samples: TrainingSample[]
  checkpoints: string[]
  lora_id: string
  lora_path: string
  job_id: string
  error: string
  log_tail: string
  peak_vram_mb: number | null
  started_at: number | null
  finished_at: number | null
  created_at: number
  updated_at: number
}

export interface LoraEntry {
  id: string
  name: string
  file: string
  target: string
  base_model: string
  trigger: string
  dataset_id: string
  run_id: string
  job_id: string
  preset: DatasetPreset
  default_multiplier: number
  size_bytes: number
  imported: boolean
  created_at: number
}

export interface TrainerStatus {
  id: string
  name: string
  upstream: string
  license: string
  targets: string[]
  installed: boolean
  fits_12gb: boolean
  reason: string
  notes: string
}

export interface TrainingStatusResponse {
  trainers: TrainerStatus[]
  weights: Record<string, Record<string, string>>
  machine_vram_mb: number
  active_run_id: string
}

export interface ImportDatasetItemsRequest {
  folder?: string
  image_paths?: string[]
  video_path?: string
  video_fps?: number
  video_max_frames?: number
  job_ids?: string[]
  analysis_id?: string
  reproduce_id?: string
}

export interface StartTrainingRequest {
  dataset_id: string
  name?: string
  config?: TrainingConfig | null
  resume_run_id?: string
}

/** A LoRA applied to a render: the registry file plus its strength (`api_types.LoraUse`). */
export interface LoraUse {
  name: string
  multiplier: number
}

export const isRunActive = (run: TrainingRun): boolean => run.status === 'queued' || run.status === 'running'
