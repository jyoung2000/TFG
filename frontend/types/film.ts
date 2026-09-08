// Film domain types — 1:1 mirror of backend/film/film_models.py (snake_case
// preserved so API payloads need no mapping layer).
//
// Cinematography vocabularies adapted from Open Media's shot axes /
// composition presets (MIT; see docs/INTEGRATED_UPSTREAMS.md), extended with
// xwide/xcu sizes, POV/dutch angles and bird/worm elevations.

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
  quality_preset: 'fast_preview' | 'balanced' | 'quality' | 'custom'
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
  created_at: number
}

export interface FilmShot {
  id: string
  order: number
  title: string
  description: string
  duration_seconds: number
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
  preview_resolution: string
  preview_max_seconds: number
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
}

export interface ContinuityWarning {
  kind: string
  message: string
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
}

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
}

export interface DirectorCommandResult {
  name: string
  ok: boolean
  result: unknown
  error: string
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
    quality_preset: 'balanced',
  }
}
