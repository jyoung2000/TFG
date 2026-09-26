/** Mirror of `backend/film/reproduce_models.py` (snake_case, no mapping layer). */

import type { PromptStyle, ShotSpec } from './shotspec'

export type ReproduceStatus = 'idle' | 'analyzing' | 'rendering' | 'scoring' | 'complete' | 'failed' | 'cancelled'
export type CandidateSource = 'render' | 'fix' | 'patch' | 'inpaint' | 'legacy'

export interface ScoreBreakdown {
  composite: number
  components: Record<string, number>
  weights_used: Record<string, number>
  missing: string[]
}

export interface ReproduceBudget {
  candidates_per_round: number
  max_rounds: number
  target_score: number
}

export interface ReproduceCandidate {
  id: string
  path: string
  prompt: string
  negative_prompt: string
  seed: number | null
  params: Record<string, unknown>
  round: number
  model: string
  target: string
  scores: ScoreBreakdown
  job_id: string
  source: CandidateSource
  parent_id: string
  created_at: number
}

export interface ReproducePatch {
  reason: string
  phrase: string
  metric: string
  value: number
}

export interface ReproduceRound {
  index: number
  prompt: string
  negative_prompt: string
  target: string
  style: string
  hints_applied: string[]
  patches: ReproducePatch[]
  seeds: number[]
  best_candidate_id: string
  best_score: number
  started_at: number
  finished_at: number | null
  note: string
}

export interface ReproduceJob {
  version: number
  id: string
  title: string
  source_path: string
  width: number
  height: number
  spec: ShotSpec
  target: string
  style: PromptStyle | null
  prompt_override: string
  prompt: string
  negative_prompt: string
  image_model: string
  vision_model: string
  budget: ReproduceBudget
  status: ReproduceStatus
  progress: number
  message: string
  error: string
  candidates: ReproduceCandidate[]
  rounds: ReproduceRound[]
  best_candidate_id: string
  reference_candidate_id: string
  picked_candidate_id: string
  why: Record<string, unknown>
  depth_path: string
  job_id: string
  created_at: number
  updated_at: number
}

export const METRIC_LABEL: Record<string, string> = {
  composite: 'Composite',
  clip: 'CLIP-I (semantic)',
  dino: 'DINOv2 (structure)',
  ssim: 'SSIM (luma)',
  palette: 'Palette ΔE2000',
  layout: 'Layout (count/IoU)',
  legacy_mae: 'Legacy pixel MAE',
}

export function isBusy(job: ReproduceJob): boolean {
  return job.status === 'analyzing' || job.status === 'rendering' || job.status === 'scoring'
}
