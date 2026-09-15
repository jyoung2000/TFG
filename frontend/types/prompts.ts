// Mirrors backend/film/prompt_compiler.py and prompt_api_types.py.

/** How a target wants its prompt shaped — the axis that actually differs. */
export type PromptStyle = 'narrative' | 'structured' | 'tagged'

/**
 * Where a convention came from. `publisher_guidance` and `tfg_default` are
 * different claims and the UI shows them differently.
 */
export type ConventionBasis = 'publisher_guidance' | 'community_convention' | 'tfg_default'

/** The common cinematic representation: one shot, before any model sees it. */
export interface ShotBrief {
  /** What the shot is for. Carried for the reader; never sent to a render model. */
  scene_intent: string
  subjects: string[]
  action: string
  location: string
  shot_size: string
  camera: string
  lens: string
  movement: string
  lighting: string
  style: string
  audio: string
  timeline: string
  continuity: string[]
  negative: string[]
}

export interface CompiledPrompt {
  model: string
  target_id: string
  target_label: string
  style: PromptStyle
  basis: ConventionBasis
  note: string
  prompt: string
  negative_prompt: string
  /** False when the model id was not recognised: the prompt is general, not tailored. */
  matched: boolean
  /** Sections the target could not carry, each with the reason. */
  dropped: string[]
}

export interface CompilePromptResponse {
  brief: ShotBrief
  prompts: CompiledPrompt[]
}

export interface PromptTarget {
  id: string
  label: string
  style: PromptStyle
  basis: ConventionBasis
  note: string
  max_chars: number
  supports_negative: boolean
  renders_audio: boolean
  renders_motion: boolean
  /** What in a model id identifies this family, so the rule is inspectable. */
  matches: string[]
}

export const EMPTY_BRIEF: ShotBrief = {
  scene_intent: '',
  subjects: [],
  action: '',
  location: '',
  shot_size: '',
  camera: '',
  lens: '',
  movement: '',
  lighting: '',
  style: '',
  audio: '',
  timeline: '',
  continuity: [],
  negative: [],
}

export const STYLE_LABELS: Record<PromptStyle, string> = {
  narrative: 'Flowing description',
  structured: 'Labelled clauses',
  tagged: 'Comma-separated tags',
}

export const BASIS_LABELS: Record<ConventionBasis, string> = {
  publisher_guidance: "The model publisher's own guidance",
  community_convention: 'The convention in common use',
  tfg_default: "This app's general default",
}

/** The brief's sections in the order a director would fill them in. */
export const BRIEF_SECTIONS: { key: keyof ShotBrief; label: string }[] = [
  { key: 'scene_intent', label: 'Scene intent' },
  { key: 'subjects', label: 'Subjects' },
  { key: 'action', label: 'Action' },
  { key: 'location', label: 'Location' },
  { key: 'shot_size', label: 'Shot size' },
  { key: 'camera', label: 'Camera' },
  { key: 'lens', label: 'Lens' },
  { key: 'movement', label: 'Movement' },
  { key: 'lighting', label: 'Lighting' },
  { key: 'style', label: 'Style' },
  { key: 'audio', label: 'Audio' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'continuity', label: 'Continuity' },
  { key: 'negative', label: 'Negative constraints' },
]

/** One section's value as text, whichever shape the field has. */
export function briefValue(brief: ShotBrief, key: keyof ShotBrief): string {
  const value = brief[key]
  return Array.isArray(value) ? value.join('; ') : value
}
