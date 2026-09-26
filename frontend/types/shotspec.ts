/**
 * Mirror of `backend/film/shot_spec.py` — the one contract between analysis
 * and generation. snake_case, no mapping layer.
 */

export type SourceKind = 'image' | 'video_shot'
export type Provenance = 'measured' | 'florence' | 'clip' | 'depth' | 'flow' | 'vlm' | 'user' | ''
export type SpecSection = 'measured' | 'subjects' | 'scene' | 'camera' | 'lighting' | 'style' | 'motion' | 'layout3d' | 'narrative'

export const SPEC_SECTIONS: SpecSection[] = ['measured', 'subjects', 'scene', 'camera', 'lighting', 'style', 'motion', 'layout3d', 'narrative']

export interface SpecSource {
  kind: SourceKind
  hash: string
  path: string
  width: number
  height: number
  aspect: string
  fps: number | null
  start: number | null
  end: number | null
}

export interface PaletteEntry {
  hex: string
  share: number
}

export interface SpecMeasured {
  palette: PaletteEntry[]
  luminance: number
  contrast: number
  saturation: number
  edge_density: number
  sharpness: number
  exif: Record<string, string>
}

export interface SpecSubject {
  label: string
  bbox: number[]
  depth_median: number | null
  count: number
  attributes: string[]
}

export interface SpecScene {
  location: string
  environment: string
  time_of_day: string
  weather: string
  fg: string
  mg: string
  bg: string
}

export interface SpecCamera {
  shot_size: string
  angle: string
  height: string
  fov_deg: number | null
  focal_mm: number | null
  lens_estimate: string
  aperture: string
  dof: string
  focus: string
  move: string
  move_intensity: number
  handheld: boolean
  roll: number
}

export interface SpecLighting {
  key_direction: string
  quality: string
  color_temp: string
  mood: string
}

export interface TagTerm {
  term: string
  score: number
}

export interface SpecStyle {
  tags: TagTerm[]
  medium: string
  artists: string[]
  negatives: string[]
}

export interface SpecMotion {
  dominant: { pan: number; tilt: number; zoom: number; roll: number }
  magnitude: number
  subject_motion: number
  pacing: string
}

export interface SpecLayoutCamera {
  pos: number[]
  rot: number[]
  fov: number
}

export interface SpecLayoutObject {
  id: string
  kind: string
  pos: number[]
  rot: number[]
  scale: number[]
  pose: string
  label: string
}

export interface SpecLayout3D {
  camera: SpecLayoutCamera
  objects: SpecLayoutObject[]
  depth_map_path: string
}

export interface SpecNarrative {
  what_happens: string
  purpose: string
  beat: string
}

export interface ShotSpec {
  version: number
  source: SpecSource
  measured: SpecMeasured
  subjects: SpecSubject[]
  scene: SpecScene
  camera: SpecCamera
  lighting: SpecLighting
  style: SpecStyle
  motion: SpecMotion
  layout3d: SpecLayout3D
  narrative: SpecNarrative
  confidence: Record<string, number>
  provenance: Record<string, string>
  locks: Record<string, boolean>
}

/** Mirror of `PromptStyle` / compile targets in `backend/film/prompt_compiler.py`. */
export type PromptStyle = 'narrative' | 'structured' | 'tagged' | 'weighted' | 'json' | 'negative_only'
export const PROMPT_STYLES: PromptStyle[] = ['narrative', 'structured', 'tagged', 'weighted', 'json', 'negative_only']
export type SpecTarget = 'ltx2' | 'wan22' | 'z_image' | 'qwen_image_edit' | 'flux' | 'sdxl' | 'cloud_generic'
export const SPEC_TARGETS: SpecTarget[] = ['ltx2', 'wan22', 'z_image', 'qwen_image_edit', 'flux', 'sdxl', 'cloud_generic']

export interface SpecParams {
  seed: number | null
  steps: number
  guidance: number
  width: number
  height: number
  duration: number
  fps: number
  resolution: string
}

export interface SpecConditioning {
  start_frame: string
  control_video: string
  depth: string
  refs: string[]
  loras: Record<string, unknown>[]
}

export interface PromptHints {
  phrases: string[]
  params: Record<string, number>
  evidence: string[]
  sample: number
}

export interface SpecCompileResult {
  target_id: string
  target_label: string
  style: PromptStyle
  prompt: string
  negative_prompt: string
  params: SpecParams
  conditioning: SpecConditioning
  dropped: string[]
  hints_applied: string[]
  matched: boolean
}
