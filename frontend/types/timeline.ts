// Mirrors backend/film/timeline_models.py and timeline_api_types.py.

export type TransitionKind = 'cut' | 'dissolve' | 'fade_in' | 'fade_out' | 'wipe' | 'dip_to_black'

export interface ShotTransition {
  kind: TransitionKind
  /** Seconds. Ignored for a cut, which is instantaneous by definition. */
  duration_seconds: number
}

export const TRANSITION_LABELS: Record<TransitionKind, string> = {
  cut: 'Cut',
  dissolve: 'Dissolve',
  fade_in: 'Fade in',
  fade_out: 'Fade out',
  wipe: 'Wipe',
  dip_to_black: 'Dip to black',
}

/** One timeline edit, with who made it. The undo snapshot stays on the server. */
export interface DirectorAction {
  id: string
  created_at: number
  action: string
  /** 'director' when a model made the edit, 'user' when a person did. */
  actor: 'director' | 'user'
  summary: string
  params: Record<string, unknown>
  affected_shot_ids: string[]
  before: null
  undone: boolean
}

export interface TimelineEntry {
  scene_id: string
  scene_title: string
  shot_id: string
  shot_title: string
  order: number
  start_seconds: number
  duration_seconds: number
  gap_before_seconds: number
  transition_in: ShotTransition
  transition_out: ShotTransition
  status: string
  has_render: boolean
}

export interface TimelineView {
  entries: TimelineEntry[]
  total_seconds: number
  shot_count: number
  rendered_count: number
}

export interface TimelineActionResult {
  action: DirectorAction
  /** The timeline after the edit, so no second call is needed. */
  timeline: TimelineView
}

export interface TimelineHistoryResult {
  actions: DirectorAction[]
  /** How many edits can still be undone. */
  undoable: number
}

/** Every edit the timeline accepts. Names match the backend's action names. */
export type TimelineActionName =
  | 'split_shot'
  | 'trim_shot'
  | 'ripple_trim'
  | 'move_shot'
  | 'reorder_shots'
  | 'insert_shot'
  | 'replace_shot'
  | 'replace_with_version'
  | 'duplicate_shot'
  | 'delete_shot'
  | 'set_transition'
  | 'set_duration'
  | 'set_gap'
  | 'build_montage'
  | 'add_opening'
  | 'add_ending'
  | 'insert_broll'
  | 'align_durations'
  | 'normalize_timeline'

export function formatSeconds(seconds: number): string {
  const whole = Math.floor(seconds)
  const minutes = Math.floor(whole / 60)
  const rest = seconds - minutes * 60
  return minutes > 0 ? `${minutes}:${rest.toFixed(1).padStart(4, '0')}` : `${rest.toFixed(1)}s`
}
