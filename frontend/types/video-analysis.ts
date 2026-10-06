// Video analysis types — 1:1 mirror of backend/film/video_analysis_models.py
// (snake_case preserved so API payloads need no mapping layer).
//
// The split between measured and inferred is deliberate and load-bearing: the
// UI shades anything a model guessed and shows its confidence, so a viewer can
// tell a timestamp from an opinion.

import type { ShotSpec } from './shotspec'

export type AnalysisDepth = 'fast' | 'standard' | 'detailed'
export type AnalysisStage =
  | 'idle'
  | 'probing'
  | 'detecting'
  | 'extracting'
  | 'analyzing'
  | 'complete'
  | 'failed'
  | 'cancelled'
export type DetectionMethod = 'cut' | 'fade' | 'uniform' | 'whole'
export type Provenance = 'measured' | 'inferred' | 'user'
export type FrameRole = 'start' | 'middle' | 'end' | 'representative'

export interface VideoSourceInfo {
  path: string
  file_name: string
  size_bytes: number
  duration_seconds: number
  fps: number
  width: number
  height: number
  aspect_ratio: string
  codec: string
  bit_rate: number
  frame_count: number
  has_audio: boolean
  audio_codec: string
  audio_channels: number
  audio_sample_rate: number
  rotation: number
  pixel_format: string
}

export interface FrameEvidence {
  path: string
  timestamp: number
  role: FrameRole
}

export interface VisualAnalysis {
  description: string
  subjects: string[]
  character_estimates: string[]
  objects: string[]
  location: string
  environment: string
  foreground: string
  midground: string
  background: string
  composition: string
  framing: string
  shot_size: string
  angle: string
  camera_height: string
  perspective: string
  lens_estimate: string
  depth_of_field: string
  focus: string
  lighting: string
  palette: string[]
  contrast: string
  visual_style: string
  production_design: string
  wardrobe: string
  props: string[]
  confidence: number
}

export interface CinematographyAnalysis {
  camera_position: string
  camera_movement: string
  movement_types: string[]
  is_static: boolean
  screen_direction: string
  eyeline: string
  ots_relationship: string
  blocking: string
  composition_rules: string[]
  confidence: number
}

export interface NarrativeAnalysis {
  what_happens: string
  who_acts: string[]
  narrative_purpose: string
  emotional_purpose: string
  story_beat: string
  setup_or_payoff: string
  continuity_implications: string[]
  pacing: string
  transition_role: string
  confidence: number
}

export interface EditorialAnalysis {
  transition_in: string
  transition_out: string
  cut_type: string
  rhythm: string
  approximate_beat: string
  montage_role: string
  broll_role: string
  confidence: number
}

export interface AudioAnalysis {
  analyzed: boolean
  dialogue: string
  transcription: string
  voiceover: string
  ambience: string
  music: string
  sfx: string[]
  silence: boolean
  emphasis: string
  rhythm: string
  confidence: number
}

export interface TextAnalysis {
  analyzed: boolean
  visible_text: string[]
  subtitles: string[]
  signs: string[]
  ui_text: string[]
  typography: string
  confidence: number
}

export interface ReversePrompts {
  storyboard: string
  video: string
  cinematography: string
  environment: string
  character: string
  motion: string
  negative: string
  /** Keyed by model id — the same shot reads differently to different models. */
  model_specific: Record<string, string>
  /** True once a person edited any field; regeneration leaves it alone. */
  edited: boolean
}

/** PromptLens 1:1 reverse-engineered prompt for one shot. */
export interface PromptLensAnalysis {
  core_prompt: string
  deep_description: string
  subject: string
  environment: string
  camera: string
  lighting: string
  style: string
  mood: string
  confidence: number
}

/** Optical flow over the shot (phase 5). Measured, never inferred. */
export interface MotionAnalysis {
  analyzed: boolean
  model: string
  pan: number
  tilt: number
  zoom: number
  roll: number
  magnitude: number
  subject_motion: number
  jitter: number
  handheld: boolean
  pacing: string
  frames_sampled: number
  confidence: number
}

export const EMPTY_MOTION: MotionAnalysis = {
  analyzed: false, model: '', pan: 0, tilt: 0, zoom: 0, roll: 0, magnitude: 0, subject_motion: 0,
  jitter: 0, handheld: false, pacing: '', frames_sampled: 0, confidence: 0,
}

export interface AnalyzedShot {
  id: string
  index: number
  start: number
  end: number
  duration: number
  detection_confidence: number
  detection_method: DetectionMethod
  boundary_edited: boolean
  frames: FrameEvidence[]
  visual: VisualAnalysis
  cinematography: CinematographyAnalysis
  narrative: NarrativeAnalysis
  editorial: EditorialAnalysis
  audio: AudioAnalysis
  text: TextAnalysis
  prompts: ReversePrompts
  prompt_lens: PromptLensAnalysis
  motion: MotionAnalysis
  /** The fused ShotSpec — what Video Reproduce renders from. */
  spec: ShotSpec
  analysis_provider: string
  analysis_model: string
  provenance: Provenance
  /** The raw model reply, so the UI can show what the answer was based on. */
  evidence_note: string
  analyzed_at: number
}

export interface VideoAnalysis {
  schema_version: number
  id: string
  title: string
  source: VideoSourceInfo
  shots: AnalyzedShot[]
  depth: AnalysisDepth
  sensitivity: number
  min_shot_seconds: number
  max_shots: number
  detect_fades: boolean
  analyze_audio: boolean
  analyze_text: boolean
  provider: string
  model: string
  stage: AnalysisStage
  progress: number
  message: string
  error: string
  reconstructed_project_id: string
  synopsis: string
  visual_style: string
  characters: string[]
  locations: string[]
  created_at: number
  updated_at: number
}

export const STAGE_META: Record<AnalysisStage, { label: string; className: string; busy: boolean }> = {
  idle: { label: 'Ready', className: 'bg-zinc-800 text-zinc-300', busy: false },
  probing: { label: 'Reading file', className: 'bg-sky-900/60 text-sky-300', busy: true },
  detecting: { label: 'Detecting shots', className: 'bg-sky-900/60 text-sky-300', busy: true },
  extracting: { label: 'Extracting frames', className: 'bg-sky-900/60 text-sky-300', busy: true },
  analyzing: { label: 'Analysing', className: 'bg-violet-900/60 text-violet-300', busy: true },
  complete: { label: 'Analysed', className: 'bg-emerald-900/60 text-emerald-300', busy: false },
  failed: { label: 'Failed', className: 'bg-red-950/70 text-red-300', busy: false },
  cancelled: { label: 'Cancelled', className: 'bg-zinc-800 text-zinc-400', busy: false },
}

export const DETECTION_METHOD_META: Record<DetectionMethod, { label: string; hint: string }> = {
  cut: { label: 'Cut', hint: 'A hard change between frames' },
  fade: { label: 'Fade', hint: 'The picture passed through black' },
  uniform: { label: 'Even split', hint: 'No cuts were found — this boundary is arbitrary' },
  whole: { label: 'Whole clip', hint: 'Too short to split' },
}

/** How to describe a confidence without implying more precision than we have. */
export function confidenceLabel(value: number): string {
  if (value <= 0) return 'not assessed'
  if (value < 0.35) return 'low confidence'
  if (value < 0.7) return 'moderate confidence'
  return 'high confidence'
}
