// Film domain types — 1:1 mirror of backend/film/film_models.py (snake_case
// preserved so API payloads need no mapping layer).
//
// Cinematography vocabularies adapted from Open Media's shot axes /
// composition presets (MIT; see docs/INTEGRATED_UPSTREAMS.md), extended with
// xwide/xcu sizes, POV/dutch angles and bird/worm elevations.

import type { TextProviderId } from './models'

export type ShotSize = 'xwide' | 'wide' | 'full' | 'medium' | 'mcu' | 'closeup' | 'xcu'
export type CameraAngle =
  | 'front'
  | 'threeQuarterLeft'
  | 'threeQuarterRight'
  | 'profile'
  | 'back'
  | 'ots'
  | 'pov'
  | 'dutch'
export type CameraElevation = 'eye' | 'low' | 'high' | 'bird' | 'worm'
export type CompositionId =
  | 'center'
  | 'leftThird'
  | 'rightThird'
  | 'upperThird'
  | 'lowerThird'
  | 'negativeSpace'
  | 'symmetrical'
  | 'leadingLines'
export type CameraMove =
  | 'static'
  | 'push_in'
  | 'pull_out'
  | 'pan_left'
  | 'pan_right'
  | 'tilt_up'
  | 'tilt_down'
  | 'dolly_left'
  | 'dolly_right'
  | 'orbit'
  | 'follow'

export const SHOT_SIZES: { id: ShotSize; label: string; hint: string }[] = [
  { id: 'xwide', label: 'Extreme Wide', hint: 'Landscape dominates; subject tiny' },
  { id: 'wide', label: 'Wide', hint: 'Full body with generous surroundings' },
  { id: 'full', label: 'Full', hint: 'Head to toe fills the frame' },
  { id: 'medium', label: 'Medium', hint: 'Waist up' },
  { id: 'mcu', label: 'Medium Close-Up', hint: 'Chest up' },
  { id: 'closeup', label: 'Close-Up', hint: 'Face fills the frame' },
  { id: 'xcu', label: 'Extreme Close-Up', hint: 'Eyes / detail only' },
]

export const CAMERA_ANGLES: { id: CameraAngle; label: string; hint: string }[] = [
  { id: 'front', label: 'Front', hint: 'Camera faces the subject' },
  { id: 'threeQuarterLeft', label: '3/4 Left', hint: '45° to the subject’s left' },
  { id: 'threeQuarterRight', label: '3/4 Right', hint: '45° to the subject’s right' },
  { id: 'profile', label: 'Profile', hint: 'Side-on' },
  { id: 'back', label: 'Back', hint: 'Behind the subject' },
  { id: 'ots', label: 'Over the Shoulder', hint: 'Past a foreground shoulder toward the subject' },
  { id: 'pov', label: 'Point of View', hint: 'Through the subject’s eyes' },
  { id: 'dutch', label: 'Dutch', hint: 'Tilted horizon' },
]

export const CAMERA_ELEVATIONS: { id: CameraElevation; label: string; hint: string }[] = [
  { id: 'worm', label: "Worm's Eye", hint: 'Ground level, looking up steeply' },
  { id: 'low', label: 'Low', hint: 'Below eye line, looking up' },
  { id: 'eye', label: 'Eye Level', hint: 'Neutral' },
  { id: 'high', label: 'High', hint: 'Above eye line, looking down' },
  { id: 'bird', label: "Bird's Eye", hint: 'Directly overhead' },
]

export const COMPOSITIONS: { id: CompositionId; label: string; screenX: number; screenY: number }[] = [
  { id: 'center', label: 'Center', screenX: 0.5, screenY: 0.5 },
  { id: 'leftThird', label: 'Left Third', screenX: 1 / 3, screenY: 0.5 },
  { id: 'rightThird', label: 'Right Third', screenX: 2 / 3, screenY: 0.5 },
  { id: 'upperThird', label: 'Upper Third', screenX: 0.5, screenY: 2 / 3 },
  { id: 'lowerThird', label: 'Lower Third', screenX: 0.5, screenY: 1 / 3 },
  { id: 'negativeSpace', label: 'Negative Space', screenX: 0.22, screenY: 0.5 },
  { id: 'symmetrical', label: 'Symmetrical', screenX: 0.5, screenY: 0.5 },
  { id: 'leadingLines', label: 'Leading Lines', screenX: 0.4, screenY: 0.45 },
]

export const CAMERA_MOVES: { id: CameraMove; label: string }[] = [
  { id: 'static', label: 'Static' },
  { id: 'push_in', label: 'Push In' },
  { id: 'pull_out', label: 'Pull Out' },
  { id: 'pan_left', label: 'Pan Left' },
  { id: 'pan_right', label: 'Pan Right' },
  { id: 'tilt_up', label: 'Tilt Up' },
  { id: 'tilt_down', label: 'Tilt Down' },
  { id: 'dolly_left', label: 'Truck Left' },
  { id: 'dolly_right', label: 'Truck Right' },
  { id: 'orbit', label: 'Orbit' },
  { id: 'follow', label: 'Follow' },
]

export function compositionTarget(id: CompositionId): { screenX: number; screenY: number } {
  const preset = COMPOSITIONS.find(c => c.id === id)
  return preset ? { screenX: preset.screenX, screenY: preset.screenY } : { screenX: 0.5, screenY: 0.5 }
}

// ---- Assets ----

export type FilmAssetKind = 'character' | 'location' | 'prop' | 'style'

export interface FilmAsset {
  id: string
  kind: FilmAssetKind
  name: string
  description: string
  appearance: string
  wardrobe: string
  accessories: string
  environment: string
  lighting: string
  atmosphere: string
  time_of_day: string
  prop_details: string
  style_prompt: string
  continuity_notes: string
  reference_images: string[]
  created_at: number
  updated_at: number
}

// ---- Composition scene (Shot Composer state) ----

export type Vec3 = [number, number, number]

export interface CompositionTransform {
  position: Vec3
  rotation: Vec3
  scale: Vec3
}

export type CompositionObjectType =
  | 'figure'
  | 'cube'
  | 'plane'
  | 'cylinder'
  | 'sphere'
  | 'cone'
  | 'camera'

export interface CompositionKeyframe {
  id: string
  time: number
  transform: CompositionTransform
  fov?: number | null
}

export type FigureVariant = 'male' | 'female' | 'child'

export interface CompositionObject {
  id: string
  name: string
  type: CompositionObjectType
  asset_id?: string | null
  visible: boolean
  /** Locked objects ignore gizmo drags and director moves. */
  locked: boolean
  transform: CompositionTransform
  pose: Record<string, Vec3>
  figure_variant: FigureVariant
  color: string
  keyframes: CompositionKeyframe[]
  fov?: number | null
}

export interface ShotFraming {
  shot_size: ShotSize
  camera_angle: CameraAngle
  camera_elevation: CameraElevation
  composition: CompositionId
  fov_deg: number
  ots_foreground_id?: string | null
  ots_subject_id?: string | null
  /** Which shoulder the OTS camera looks over. */
  ots_shoulder: 'left' | 'right'
  /** "preset": camera re-solved from presets; "manual": user-positioned camera wins. */
  camera_mode: 'preset' | 'manual'
}

export interface CompositionScene {
  objects: CompositionObject[]
  camera: CompositionObject | null
  framing: ShotFraming
  camera_move: CameraMove
  duration_seconds: number
}

export interface FilmPose {
  id: string
  name: string
  category: string
  joints: Record<string, Vec3>
}

// ---- Shots ----

export type ShotStatus =
  | 'draft'
  | 'composed'
  | 'ready'
  | 'queued'
  | 'generating'
  | 'review'
  | 'approved'
  | 'rejected'
export type VersionKind = 'preview' | 'final'
export type VersionStatus = 'queued' | 'generating' | 'complete' | 'failed' | 'cancelled'

export interface ShotCharacter {
  asset_id: string
  pose_name: string
  emotion: string
  position_hint: string
}

export interface ShotGenerationSettings {
  model: string
  resolution: string
  fps: number
  seed: number | null
  aspect_ratio: '16:9' | '9:16'
  use_capture_as_reference: boolean
  continue_from_previous: boolean
  quality_preset: QualityPreset
}

export interface ShotVersion {
  number: number
  kind: VersionKind
  status: VersionStatus
  prompt: string
  negative_prompt: string
  model: string
  resolution: string
  fps: number
  duration_seconds: number
  seed: number | null
  capture_path: string
  output_path: string
  error: string
  wardrobe_snapshot: Record<string, string>
  /** Shot settings at render time (framing, camera move, cast, generation). */
  shot_snapshot: Record<string, unknown>
  generation_seconds: number | null
  gpu_name: string
  /** Estimate: VRAM used after the job, not a true peak. */
  peak_vram_gb: number | null
  execution_mode: string
  created_at: number
}

export interface FilmShot {
  id: string
  order: number
  title: string
  description: string
  duration_seconds: number
  /** Overrides the scene/project inter-shot gap before this shot. */
  gap_before_seconds: number | null
  framing: ShotFraming
  camera_move: CameraMove
  characters: ShotCharacter[]
  location_id: string | null
  prop_ids: string[]
  action: string
  dialogue: string
  emotion: string
  visual_prompt: string
  negative_prompt: string
  prompt_locked: boolean
  composition: CompositionScene | null
  capture_path: string
  generation: ShotGenerationSettings
  versions: ShotVersion[]
  current_version: number | null
  status: ShotStatus
  created_at: number
  updated_at: number
}

// ---- Scenes / project ----

export interface FilmScene {
  id: string
  order: number
  title: string
  description: string
  location_id: string | null
  character_ids: string[]
  prop_ids: string[]
  mood: string
  lighting: string
  time_of_day: string
  continuity_notes: string
  /** Overrides the project inter-shot gap for this scene. */
  inter_shot_gap_seconds: number | null
  shots: FilmShot[]
}

export interface FilmScript {
  content: string
  updated_at: number
}

export interface FilmProjectSettings {
  default_model: string
  default_resolution: string
  style_prompt: string
  default_negative_prompt: string
  inter_shot_gap_seconds: number
  strict_continuity: boolean
  default_quality_preset: 'fast_preview' | 'balanced' | 'quality' | 'custom'
  preview_resolution: string
  preview_max_seconds: number
  /** '' follows the app default; 'local' keeps this film's frames on this machine. */
  media_provider: '' | 'local' | 'fal' | 'wavespeed' | 'replicate'
  /** Provider-scoped model ids used when media_provider is a hosted one. */
  video_model: string
  image_model: string
}

export interface FilmProject {
  schema_version: number
  id: string
  name: string
  script: FilmScript
  settings: FilmProjectSettings
  assets: FilmAsset[]
  scenes: FilmScene[]
  pose_library: FilmPose[]
  created_at: number
  updated_at: number
}

// ---- Queue / capabilities / director ----

export interface QueuedJob {
  project_id: string
  scene_id: string
  shot_id: string
  shot_title: string
  kind: VersionKind
  version_number: number
  status: string
}

export interface FilmQueue {
  active: QueuedJob | null
  pending: QueuedJob[]
  paused: boolean
  /** Host generation progress (0-100) for the active job. */
  progress: number | null
  phase: string
}

export type ContinuityLevel = 'good' | 'minor' | 'significant' | 'broken'
export type ContinuitySeverity = 'minor' | 'significant' | 'broken'

export interface ContinuityWarning {
  kind: string
  message: string
  severity: ContinuitySeverity
  /** Human-readable suggested fix. */
  fix: string
  /** True when the backend can repair it via POST …/continuity/{shot}/fix. */
  auto_fixable: boolean
  subject_id: string
}

export interface ContinuityReport {
  level: ContinuityLevel
  warnings: ContinuityWarning[]
}

export type VisualReviewCategory = 'good' | 'minor_drift' | 'review_recommended' | 'likely_break' | 'unavailable'

export const VISUAL_REVIEW_META: Record<VisualReviewCategory, { label: string; className: string }> = {
  good: { label: 'Good', className: 'text-emerald-300' },
  minor_drift: { label: 'Minor drift', className: 'text-amber-200' },
  review_recommended: { label: 'Review recommended', className: 'text-orange-300' },
  likely_break: { label: 'Likely continuity break', className: 'text-red-300' },
  unavailable: { label: 'Not available', className: 'text-zinc-500' },
}

export interface VisualReview {
  available: boolean
  reason: string
  category: VisualReviewCategory
  summary: string
  issues: string[]
  previous_shot_id: string | null
  previous_frame_path: string
  current_frame_path: string
  context: DirectorContextDetails | null
}

export interface ProjectContinuity {
  level: ContinuityLevel
  shots: { shot_id: string; scene_id: string; level: ContinuityLevel; warning_count: number }[]
  counts: Record<string, number>
}

export const CONTINUITY_LEVEL_META: Record<ContinuityLevel, { label: string; dot: string; text: string }> = {
  good: { label: 'Continuity good', dot: 'bg-emerald-400', text: 'text-emerald-300' },
  minor: { label: 'Minor continuity notes', dot: 'bg-amber-300', text: 'text-amber-200' },
  significant: { label: 'Significant continuity issues', dot: 'bg-orange-400', text: 'text-orange-300' },
  broken: { label: 'Continuity broken', dot: 'bg-red-500', text: 'text-red-300' },
}

export interface PackageSummary {
  project_id: string
  project_name: string
  schema_version: number
  scenes: number
  shots: number
  assets: number
  media_files: number
  includes_outputs: boolean
  total_bytes: number
  warnings: string[]
  path: string
}

export type QualityPreset = 'project' | 'fast_preview' | 'balanced' | 'quality' | 'custom'

export interface FilmQualityProfile {
  id: QualityPreset
  label: string
  model: string
  resolution: string
  description: string
  recommended: boolean
  fits_gpu: boolean | null
}

export interface FilmModelCapability {
  id: string
  label: string
  modes: string[]
  supports_image_to_video: boolean
  supports_text_to_video: boolean
  supports_reference_images: boolean
  supports_audio: boolean
  downloaded: boolean
  download_state: 'downloaded' | 'not_downloaded' | 'managed_by_wangp' | 'cloud' | 'not_configured'
  execution: 'local' | 'wangp' | 'api'
  required: boolean
  disk_size_gb: number | null
  estimated_min_vram_gb: number | null
  fits_gpu: boolean | null
  supported_resolutions: string[]
  family: string
  task: string
  description: string
  quantization: string
  state: ModelState
  installed_size_gb: number | null
  is_active: boolean
  vram_is_estimate: boolean
}

export type ModelState =
  | 'active'
  | 'installed'
  | 'available'
  | 'downloading'
  | 'update_available'
  | 'incompatible'
  | ''

export interface FilmCapabilities {
  gpu_name: string | null
  gpu_vram_gb: number | null
  execution_mode: 'wangp' | 'api' | 'local'
  gpu_verdict: string
  gpu_verdict_level: 'ok' | 'partial' | 'none'
  models: FilmModelCapability[]
  total_required_download_gb: number | null
  text_encoder_optional: boolean
  vram_note: string
  profiles: FilmQualityProfile[]
  /** Where model weights live on disk (WanGP ckpts or the app models dir). */
  models_path: string
  system_ram_gb: number | null
  cuda_available: boolean
}

export interface DirectorCommandResult {
  name: string
  ok: boolean
  result: unknown
  error: string
}

/** What the backend sent to the model — shown as "context details" in the UI. */
export interface DirectorContextDetails {
  provider: string
  model: string
  role: string
  steps: number
  tool_calls: number
  prompt_chars: number
  project_summary_chars: number
  prompt_tokens: number | null
  completion_tokens: number | null
  scope: string
}

export interface DirectorChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface DirectorInstructResponse {
  plan_summary: string
  results: DirectorCommandResult[]
  reply: string
  context: DirectorContextDetails | null
}

export interface DirectorChatResponse {
  reply: string
  suggested_prompt: string
  suggested_negative_prompt: string
  suggested_duration_seconds: number | null
  context: DirectorContextDetails
}

export type DirectorRole = 'script' | 'storyboard' | 'director' | 'continuity' | 'prompt_refinement'

export const DIRECTOR_ROLES: { id: DirectorRole; label: string; hint: string }[] = [
  { id: 'director', label: 'Director', hint: 'Natural-language commands in the storyboard' },
  { id: 'script', label: 'Script', hint: 'Build Film with AI — idea to screenplay and shot plan' },
  { id: 'storyboard', label: 'Storyboard', hint: 'Script to cinematographed shots' },
  { id: 'prompt_refinement', label: 'Prompt refinement', hint: 'Rewrites shot prompts and Quick Mode ideas' },
  { id: 'continuity', label: 'Continuity', hint: 'Continuity explanations and fixes' },
]

export type DirectorProviderSetting = 'auto' | TextProviderId

/** One text provider the AI Director can run on. */
export interface DirectorProviderStatus {
  id: TextProviderId
  label: string
  configured: boolean
  /** The model this provider would use right now ('' = the provider's default). */
  model: string
  /** False when the provider needs no key (a local OpenAI-compatible server). */
  needs_key: boolean
  note: string
}

export interface DirectorStatus {
  provider_setting: DirectorProviderSetting
  active_provider: TextProviderId | 'none'
  gemini_configured: boolean
  openrouter_configured: boolean
  openai_compatible_configured: boolean
  anthropic_configured: boolean
  xai_configured: boolean
  openrouter_key_source: 'settings' | 'env' | 'none'
  roles: { role: DirectorRole; provider: string; model: string }[]
  tools: { name: string; description: string }[]
  providers: DirectorProviderStatus[]
  message: string
}

export interface OpenRouterModelInfo {
  id: string
  name: string
  context_length: number | null
  prompt_price: string
  completion_price: string
  supports_tools: boolean
  supports_json: boolean
}

export interface OpenRouterValidation {
  valid: boolean
  label: string
  usage: number | null
  limit: number | null
  is_free_tier: boolean | null
  message: string
}

// ---- Build Film with AI ----

export interface FilmBuildShot {
  title: string
  description: string
  action: string
  dialogue: string
  shot_size: ShotSize
  camera_angle: CameraAngle
  camera_elevation: CameraElevation
  composition: CompositionId
  camera_move: CameraMove
  duration_seconds: number
  characters: string[]
  location: string
}

export interface FilmBuildScene {
  title: string
  description: string
  location: string
  time_of_day: string
  mood: string
  lighting: string
  characters: string[]
  shots: FilmBuildShot[]
}

export interface FilmBuildCharacter {
  name: string
  description: string
  appearance: string
  wardrobe: string
}

export interface FilmBuildLocation {
  name: string
  description: string
  environment: string
  lighting: string
  atmosphere: string
}

export interface FilmBuildPlan {
  title: string
  logline: string
  style: string
  script: string
  characters: FilmBuildCharacter[]
  locations: FilmBuildLocation[]
  scenes: FilmBuildScene[]
}

export const SHOT_STATUS_META: Record<ShotStatus, { label: string; className: string }> = {
  draft: { label: 'Draft', className: 'bg-zinc-700 text-zinc-300' },
  composed: { label: 'Composed', className: 'bg-sky-900/70 text-sky-300' },
  ready: { label: 'Ready', className: 'bg-indigo-900/70 text-indigo-300' },
  queued: { label: 'Queued', className: 'bg-amber-900/70 text-amber-300' },
  generating: { label: 'Generating', className: 'bg-amber-800/80 text-amber-200 animate-pulse' },
  review: { label: 'Review', className: 'bg-violet-900/70 text-violet-300' },
  approved: { label: 'Approved', className: 'bg-emerald-900/70 text-emerald-300' },
  rejected: { label: 'Rejected', className: 'bg-red-900/70 text-red-300' },
}

export function framingLabel(framing: ShotFraming): string {
  const size = SHOT_SIZES.find(s => s.id === framing.shot_size)?.label ?? framing.shot_size
  const angle = CAMERA_ANGLES.find(a => a.id === framing.camera_angle)?.label ?? framing.camera_angle
  return `${size} · ${angle}`
}

export function defaultGenerationSettings(): ShotGenerationSettings {
  return {
    model: '',
    resolution: '',
    fps: 24,
    seed: null,
    aspect_ratio: '16:9',
    use_capture_as_reference: true,
    continue_from_previous: false,
    quality_preset: 'project',
  }
}
