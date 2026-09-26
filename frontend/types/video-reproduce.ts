/** Mirror of `backend/film/video_reproduce_models.py` (snake_case, no mapping layer). */

import type { ScoreBreakdown } from './reproduce'

export type VideoReproduceStatus = 'idle' | 'running' | 'complete' | 'failed' | 'cancelled'
export type CandidateStatus = 'queued' | 'generating' | 'complete' | 'failed' | 'cancelled'

export interface VideoCandidate {
  id: string
  version_number: number
  /** Absolute output path of the rendered clip (served through the media route). */
  path: string
  /** Reproduce-relative frame thumbnails: start / middle / end. */
  frames: string[]
  prompt: string
  negative_prompt: string
  seed: number | null
  round: number
  model: string
  target: string
  duration_seconds: number
  status: CandidateStatus
  error: string
  scores: ScoreBreakdown
  motion_match: number | null
  job_id: string
  created_at: number
}

export interface ReproduceShot {
  shot_id: string
  index: number
  film_scene_id: string
  film_shot_id: string
  start: number
  end: number
  duration_seconds: number
  start_frame: string
  prompt: string
  negative_prompt: string
  prompt_source: 'spec' | 'analysis' | 'user'
  candidates: VideoCandidate[]
  best_candidate_id: string
  picked_candidate_id: string
}

export interface VideoReproduceJob {
  version: number
  analysis_id: string
  project_id: string
  title: string
  kind: 'preview' | 'final'
  target: string
  model: string
  resolution: string
  fps: number
  candidates_per_shot: number
  rounds: number
  seed: number | null
  status: VideoReproduceStatus
  progress: number
  message: string
  error: string
  shots: ReproduceShot[]
  stitched_path: string
  stitched_at: number | null
  job_id: string
  peak_vram_mb: number | null
  created_at: number
  updated_at: number
}

export interface VideoReproduceRequest {
  candidates: number
  rounds: number
  shot_ids: string[]
  kind?: 'preview' | 'final'
  seed?: number | null
}

export function chosenCandidate(shot: ReproduceShot): VideoCandidate | null {
  return shot.candidates.find(c => c.id === shot.picked_candidate_id) ?? shot.candidates.find(c => c.id === shot.best_candidate_id) ?? null
}
