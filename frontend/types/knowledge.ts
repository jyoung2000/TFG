// Mirrors backend/film/knowledge_models.py and knowledge_api_types.py.
// snake_case on purpose — no mapping layer, same as types/film.ts.

export type EventKind =
  | 'generation_completed'
  | 'generation_failed'
  | 'generation_cancelled'
  | 'version_approved'
  | 'version_rejected'
  | 'version_promoted'
  | 'version_deleted'
  | 'prompt_edited'
  | 'negative_prompt_edited'
  | 'model_changed'
  | 'provider_changed'
  | 'continuity_corrected'
  | 'storyboard_corrected'
  | 'timeline_changed'
  | 'rating'
  | 'feedback'

export type EventCategory = 'generation' | 'approval' | 'editing' | 'feedback'

/**
 * How much weight a statement deserves. `fact` is arithmetic over recorded
 * events; `hypothesis` is a guess from too little evidence. The UI shows the
 * kind next to every statement so the two never read alike.
 */
export type ObservationKind =
  | 'fact'
  | 'observed_pattern'
  | 'user_preference'
  | 'model_recommendation'
  | 'hypothesis'

export type KnowledgeTask = 'video' | 'image' | 'text' | ''

export interface KnowledgeEvent {
  id: string
  created_at: number
  kind: EventKind
  category: EventCategory
  project_id: string
  scene_id: string
  shot_id: string
  version_number: number | null
  model: string
  provider: string
  task: KnowledgeTask
  execution_mode: string
  prompt: string
  negative_prompt: string
  outcome: string
  duration_seconds: number | null
  error: string
  rating: number | null
  note: string
}

export interface Observation {
  id: string
  model: string
  provider: string
  task: KnowledgeTask
  kind: ObservationKind
  statement: string
  confidence: number
  support_count: number
  contradiction_count: number
  sample_size: number
  first_seen: number
  last_seen: number
  evidence_event_ids: string[]
}

/**
 * How one piece of prompt vocabulary has fared with one model. Counted, not
 * asserted: the verdict stays `unclear` until the phrase has been used enough
 * times to mean anything.
 */
export interface PromptPattern {
  phrase: string
  uses: number
  successes: number
  failures: number
  approvals: number
  rejections: number
  confidence: number
  verdict: 'worked' | 'struggled' | 'unclear'
}

export interface ModelProfile {
  model: string
  provider: string
  task: KnowledgeTask
  label: string

  // Declared by the provider or the local catalog — not measured here.
  supports_image_input: boolean
  supports_negative_prompt: boolean
  supports_camera_control: boolean
  max_duration_seconds: number | null
  supported_aspect_ratios: string[]
  context_length: number | null
  prompt_convention: string

  // Measured here, from this user's own runs.
  runs: number
  successes: number
  failures: number
  cancellations: number
  approvals: number
  rejections: number
  average_seconds: number | null
  average_rating: number | null
  last_used_at: number

  observations: Observation[]
  prompt_patterns: PromptPattern[]
}

export interface LearningSettings {
  enabled: boolean
  generation: boolean
  approval: boolean
  editing: boolean
  feedback: boolean
}

export interface KnowledgeSummary {
  learning: LearningSettings
  event_count: number
  model_count: number
  observation_count: number
  /** Where the knowledge lives, so the user can find or delete it. */
  database: string
  updated_at: number
}

export interface KnowledgeExport {
  schema_version: number
  exported_at: number
  events: KnowledgeEvent[]
  observations: Observation[]
}

export interface RecommendResponse {
  model: string
  /** Cites the evidence, so the user can disagree with it. */
  reason: string
}

/** Rates measured over recorded runs, or null when nothing has been recorded. */
export function successRate(profile: ModelProfile): number | null {
  const attempts = profile.successes + profile.failures
  return attempts ? profile.successes / attempts : null
}

export function approvalRate(profile: ModelProfile): number | null {
  const judged = profile.approvals + profile.rejections
  return judged ? profile.approvals / judged : null
}

export const OBSERVATION_KIND_LABELS: Record<ObservationKind, string> = {
  fact: 'Fact',
  observed_pattern: 'Observed pattern',
  user_preference: 'Your preference',
  model_recommendation: 'Recommendation',
  hypothesis: 'Hypothesis',
}
