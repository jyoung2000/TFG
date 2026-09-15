/**
 * The knowledge engine, simulated.
 *
 * Derivation is real here, not canned: the same thresholds as the Python
 * handler, applied to the same event log, so the UI-only build shows a
 * hypothesis where the app would show a hypothesis. The seed is a handful of
 * plausible renders, enough that one model has earned a pattern and another
 * has not.
 */

import type {
  KnowledgeEvent,
  KnowledgeExport,
  EventCategory,
  KnowledgeSummary,
  LearningSettings,
  ModelProfile,
  Observation,
  ObservationKind,
  PromptPattern,
} from '../../../frontend/types/knowledge'
import { MockHttpError, type Router } from '../http'
import type { MockState, Store } from '../state'

const PATTERN_MIN_SAMPLE = 5
const PREFERENCE_MIN_SAMPLE = 3
const PHRASE_MIN_USES = 3

const KIND_RANK: Record<ObservationKind, number> = {
  fact: 0,
  observed_pattern: 1,
  user_preference: 2,
  model_recommendation: 3,
  hypothesis: 4,
}

const PHRASES = [
  'extreme close-up', 'close-up', 'medium shot', 'wide shot', 'establishing shot',
  'static', 'handheld', 'dolly in', 'tracking shot', 'pan', 'tilt', 'push in',
  'wide angle', 'telephoto', 'anamorphic', 'shallow depth of field', 'bokeh',
  'golden hour', 'blue hour', 'backlit', 'rim light', 'low key', 'soft light',
  'silhouette', 'neon', 'overcast', 'cinematic', 'photorealistic', 'film grain',
  'lens flare', 'desaturated', 'high contrast', 'muted palette', 'monochrome',
  'slow motion', 'time lapse',
]

/** Which learning switch governs each event kind, and which category it is. */
const CATEGORY_OF: Record<string, EventCategory> = {
  generation_completed: 'generation',
  generation_failed: 'generation',
  generation_cancelled: 'generation',
  version_approved: 'approval',
  version_rejected: 'approval',
  version_promoted: 'approval',
  version_deleted: 'approval',
  prompt_edited: 'editing',
  negative_prompt_edited: 'editing',
  model_changed: 'editing',
  provider_changed: 'editing',
  continuity_corrected: 'editing',
  storyboard_corrected: 'editing',
  timeline_changed: 'editing',
  rating: 'feedback',
  feedback: 'feedback',
}

function confidenceFor(sample: number): number {
  if (sample <= 0) return 0
  return Math.round((sample / (sample + 5)) * 1000) / 1000
}

let counter = 0
function nextId(prefix: string): string {
  counter += 1
  return `${prefix}-${counter.toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

function event(partial: Partial<KnowledgeEvent>): KnowledgeEvent {
  return {
    id: partial.id || nextId('ev'),
    created_at: partial.created_at ?? Date.now(),
    kind: partial.kind ?? 'generation_completed',
    category: partial.category ?? CATEGORY_OF[partial.kind ?? 'generation_completed'] ?? 'generation',
    project_id: partial.project_id ?? '',
    scene_id: partial.scene_id ?? '',
    shot_id: partial.shot_id ?? '',
    version_number: partial.version_number ?? null,
    model: partial.model ?? '',
    provider: partial.provider ?? '',
    task: partial.task ?? 'video',
    execution_mode: partial.execution_mode ?? '',
    prompt: partial.prompt ?? '',
    negative_prompt: partial.negative_prompt ?? '',
    outcome: partial.outcome ?? '',
    duration_seconds: partial.duration_seconds ?? null,
    error: partial.error ?? '',
    rating: partial.rating ?? null,
    note: partial.note ?? '',
  }
}

/**
 * A history that is worth looking at: one model with enough runs to have
 * earned a pattern, one with too few, and one that keeps failing the same way.
 */
export function seedKnowledge(): KnowledgeEvent[] {
  const day = 86_400_000
  const now = Date.now()
  const events: KnowledgeEvent[] = []

  const dependable = 'ltxv-13b-098-dev'
  for (let i = 0; i < 9; i += 1) {
    events.push(event({
      kind: i === 7 ? 'generation_failed' : 'generation_completed',
      model: dependable, provider: 'wangp', execution_mode: 'wangp',
      prompt: i % 2 === 0 ? 'golden hour, slow motion, cinematic wide shot' : 'handheld close-up, film grain',
      outcome: i === 7 ? 'failure' : 'success',
      duration_seconds: 34 + i, error: i === 7 ? 'CUDA out of memory' : '',
      created_at: now - (12 - i) * day, project_id: 'demo-film',
    }))
  }
  for (let i = 0; i < 5; i += 1) {
    events.push(event({
      kind: i === 4 ? 'version_rejected' : 'version_approved',
      model: dependable, provider: 'wangp',
      prompt: 'golden hour, slow motion, cinematic wide shot',
      created_at: now - (6 - i) * day, project_id: 'demo-film',
    }))
  }

  // Two runs, one of which failed. Not enough to conclude anything — which is
  // the point: the engine must say so rather than call it a pattern.
  const untested = 'wan2.2-t2v-a14b'
  for (let i = 0; i < 2; i += 1) {
    const failed = i === 1
    events.push(event({
      kind: failed ? 'generation_failed' : 'generation_completed',
      model: untested, provider: 'wangp', execution_mode: 'wangp',
      prompt: 'neon, anamorphic, tracking shot',
      outcome: failed ? 'failure' : 'success',
      duration_seconds: failed ? null : 71 + i,
      error: failed ? 'Out of memory during VAE decode' : '',
      created_at: now - (3 - i) * day, project_id: 'demo-film',
    }))
  }

  const struggling = 'fal:minimax-video'
  for (let i = 0; i < 6; i += 1) {
    const failed = i < 4
    events.push(event({
      kind: failed ? 'generation_failed' : 'generation_completed',
      model: struggling, provider: 'fal', execution_mode: 'api',
      prompt: 'extreme close-up, shallow depth of field',
      outcome: failed ? 'failure' : 'success', duration_seconds: failed ? null : 22,
      error: failed ? 'Upstream rejected the request: content policy' : '',
      created_at: now - (9 - i) * day, project_id: 'demo-film',
    }))
  }

  return events
}

function totalsFor(events: KnowledgeEvent[]) {
  const durations = events.map(e => e.duration_seconds).filter((d): d is number => d !== null)
  const ratings = events.map(e => e.rating).filter((r): r is number => r !== null)
  return {
    runs: events.length,
    successes: events.filter(e => e.kind === 'generation_completed').length,
    failures: events.filter(e => e.kind === 'generation_failed').length,
    cancellations: events.filter(e => e.kind === 'generation_cancelled').length,
    approvals: events.filter(e => e.kind === 'version_approved').length,
    rejections: events.filter(e => e.kind === 'version_rejected').length,
    average_seconds: durations.length
      ? Math.round((durations.reduce((a, b) => a + b, 0) / durations.length) * 100) / 100
      : null,
    average_rating: ratings.length
      ? Math.round((ratings.reduce((a, b) => a + b, 0) / ratings.length) * 100) / 100
      : null,
    last_used_at: events.length ? Math.max(...events.map(e => e.created_at)) : 0,
  }
}

function deriveObservations(model: string, events: KnowledgeEvent[]): Observation[] {
  if (events.length === 0) return []
  const t = totalsFor(events)
  const attempts = t.successes + t.failures
  const judged = t.approvals + t.rejections
  const provider = events.find(e => e.provider)?.provider ?? ''
  const evidence = events.slice(0, 8).map(e => e.id)
  const firstSeen = Math.min(...events.map(e => e.created_at))
  const lastSeen = Math.max(...events.map(e => e.created_at))

  const make = (kind: ObservationKind, statement: string, sample: number, support = 0, against = 0): Observation => ({
    id: nextId('ob'),
    model,
    provider,
    task: 'video',
    kind,
    statement,
    confidence: kind === 'fact' ? 1 : confidenceFor(sample),
    support_count: support,
    contradiction_count: against,
    sample_size: sample,
    first_seen: firstSeen,
    last_seen: lastSeen,
    evidence_event_ids: evidence,
  })

  const out: Observation[] = []
  if (attempts) out.push(make('fact', `Completed ${t.successes} of ${attempts} renders here.`, attempts, t.successes, t.failures))
  if (judged) out.push(make('fact', `You approved ${t.approvals} of ${judged} results.`, judged, t.approvals, t.rejections))
  if (t.average_seconds !== null && attempts) out.push(make('fact', `Averages ${t.average_seconds.toFixed(1)}s per job.`, attempts))

  if (attempts) {
    const failureRate = t.failures / attempts
    const kind: ObservationKind = attempts >= PATTERN_MIN_SAMPLE ? 'observed_pattern' : 'hypothesis'
    if (failureRate >= 0.5) {
      out.push(make(kind, 'Fails more often than it succeeds on this machine.', attempts, t.failures, t.successes))
    } else if (failureRate === 0 && attempts >= PATTERN_MIN_SAMPLE) {
      out.push(make('observed_pattern', 'Has not failed here yet.', attempts, t.successes))
    }
  }

  if (judged) {
    const approvalRate = t.approvals / judged
    const kind: ObservationKind = judged >= PREFERENCE_MIN_SAMPLE ? 'user_preference' : 'hypothesis'
    if (approvalRate >= 0.7) out.push(make(kind, 'You usually keep what this model produces.', judged, t.approvals, t.rejections))
    else if (approvalRate <= 0.3) out.push(make(kind, 'You usually reject what this model produces.', judged, t.rejections, t.approvals))
  }

  if (attempts >= PATTERN_MIN_SAMPLE && t.successes / attempts >= 0.8 && (!judged || t.approvals >= t.rejections)) {
    out.push(make('model_recommendation', 'A dependable default for this kind of shot.', attempts, t.successes))
  }

  const errors = new Map<string, number>()
  for (const e of events) {
    if (e.kind !== 'generation_failed' || !e.error) continue
    const key = e.error.split('.')[0].split(':')[0].trim().slice(0, 120)
    if (key) errors.set(key, (errors.get(key) ?? 0) + 1)
  }
  const worst = [...errors.entries()].sort((a, b) => b[1] - a[1])[0]
  if (worst && worst[1] >= 2) {
    out.push(make(worst[1] >= 3 ? 'observed_pattern' : 'hypothesis', `Recurring failure: ${worst[0]}`, worst[1], worst[1]))
  }

  out.sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind] || b.confidence - a.confidence)
  return out
}

function derivePatterns(events: KnowledgeEvent[]): PromptPattern[] {
  const tally = new Map<string, PromptPattern>()
  for (const e of events) {
    const prompt = e.prompt.toLowerCase()
    if (!prompt) continue
    for (const phrase of PHRASES) {
      if (!prompt.includes(phrase)) continue
      const entry = tally.get(phrase) ?? {
        phrase, uses: 0, successes: 0, failures: 0, approvals: 0, rejections: 0,
        confidence: 0, verdict: 'unclear' as const,
      }
      entry.uses += 1
      if (e.kind === 'generation_completed') entry.successes += 1
      else if (e.kind === 'generation_failed') entry.failures += 1
      else if (e.kind === 'version_approved') entry.approvals += 1
      else if (e.kind === 'version_rejected') entry.rejections += 1
      tally.set(phrase, entry)
    }
  }
  const patterns = [...tally.values()].map(p => {
    const good = p.successes + p.approvals
    const judged = good + p.failures + p.rejections
    let verdict: PromptPattern['verdict'] = 'unclear'
    if (judged >= PHRASE_MIN_USES) {
      const rate = good / judged
      if (rate >= 0.7) verdict = 'worked'
      else if (rate <= 0.4) verdict = 'struggled'
    }
    return { ...p, confidence: confidenceFor(judged), verdict }
  })
  patterns.sort((a, b) => b.uses - a.uses || a.phrase.localeCompare(b.phrase))
  return patterns
}

function profilesFrom(events: KnowledgeEvent[]): ModelProfile[] {
  const models = [...new Set(events.map(e => e.model).filter(Boolean))]
  const profiles = models.map(model => {
    const mine = events.filter(e => e.model === model)
    const t = totalsFor(mine)
    return {
      model,
      provider: mine.find(e => e.provider)?.provider ?? '',
      task: 'video' as const,
      label: model,
      supports_image_input: false,
      supports_negative_prompt: true,
      supports_camera_control: false,
      max_duration_seconds: null,
      supported_aspect_ratios: [],
      context_length: null,
      prompt_convention: '',
      ...t,
      observations: deriveObservations(model, mine),
      prompt_patterns: derivePatterns(mine),
    }
  })
  profiles.sort((a, b) => b.last_used_at - a.last_used_at)
  return profiles
}

export function registerKnowledgeRoutes(router: Router, store: Store): void {
  const learning = (): LearningSettings => store.data.learning
  const allows = (kind: string): boolean => {
    const settings = learning()
    if (!settings.enabled) return false
    const category = CATEGORY_OF[kind]
    return category ? settings[category] : true
  }

  router.get('/api/knowledge', (): KnowledgeSummary => {
    const profiles = profilesFrom(store.data.knowledge)
    return {
      learning: learning(),
      event_count: store.data.knowledge.length,
      model_count: profiles.length,
      observation_count: profiles.reduce((n, p) => n + p.observations.length, 0),
      database: '~/Movies/LTX Desktop/knowledge/knowledge.db (simulated)',
      updated_at: Date.now(),
    }
  })

  router.get('/api/knowledge/models', () => ({ models: profilesFrom(store.data.knowledge) }))

  router.get('/api/knowledge/events', req => {
    const projectId = req.query.get('project_id') ?? ''
    const limit = Number(req.query.get('limit') ?? 100) || 100
    return store.data.knowledge
      .filter(e => !projectId || e.project_id === projectId)
      .slice()
      .sort((a, b) => b.created_at - a.created_at)
      .slice(0, limit)
  })

  router.put('/api/knowledge/settings', req => {
    const body = req.body as Partial<LearningSettings>
    return store.mutate(state => {
      state.learning = { ...state.learning, ...body }
      return state.learning
    })
  })

  router.post('/api/knowledge/feedback', req => {
    const body = (req.body as { model?: string; provider?: string; project_id?: string; shot_id?: string; rating?: number; note?: string })
    const kind = body.rating !== undefined && body.rating !== null ? 'rating' : 'feedback'
    if (!allows(kind)) return { status: 'declined' }
    store.mutate(state => {
      state.knowledge.push(event({
        kind, model: body.model ?? '', provider: body.provider ?? '',
        project_id: body.project_id ?? '', shot_id: body.shot_id ?? '',
        rating: body.rating ?? null, note: body.note ?? '',
      }))
    })
    return { status: 'ok' }
  })

  router.post('/api/knowledge/recommend', req => {
    const body = (req.body as { task?: string; candidates?: string[] })
    const candidates = body.candidates ?? []
    if (candidates.length === 0) return { model: '', reason: 'No eligible models.' }
    const profiles = new Map(profilesFrom(store.data.knowledge).map(p => [p.model, p]))
    let best = candidates[0]
    let bestScore = -1
    let reason = 'No usage history yet, so this is not a recommendation.'
    for (const model of candidates) {
      const profile = profiles.get(model)
      const attempts = (profile?.successes ?? 0) + (profile?.failures ?? 0)
      if (!profile || attempts === 0) continue
      const success = profile.successes / attempts
      const judged = profile.approvals + profile.rejections
      const approval = judged ? profile.approvals / judged : 0.5
      const score = (0.6 * success + 0.4 * approval) * confidenceFor(attempts)
      if (score > bestScore) {
        bestScore = score
        best = model
        reason = `Completed ${profile.successes} of ${attempts} renders here${judged ? `, and you kept ${profile.approvals} of ${judged}` : ''}.`
      }
    }
    return { model: best, reason }
  })

  router.get('/api/knowledge/export', (): KnowledgeExport => ({
    schema_version: 1,
    exported_at: Date.now(),
    events: store.data.knowledge,
    observations: profilesFrom(store.data.knowledge).flatMap(p => p.observations),
  }))

  router.post('/api/knowledge/import', req => {
    const body = (req.body as { payload?: KnowledgeExport; replace?: boolean })
    const payload = body.payload
    if (!payload || payload.schema_version !== 1) {
      throw new MockHttpError(400, `Unsupported knowledge export version: ${payload?.schema_version ?? 'missing'}`)
    }
    return store.mutate(state => {
      if (body.replace) state.knowledge = []
      const known = new Set(state.knowledge.map(e => e.id))
      for (const incoming of payload.events ?? []) {
        if (!known.has(incoming.id)) state.knowledge.push(incoming)
      }
      return { status: `imported ${(payload.events ?? []).length}` }
    })
  })

  router.post('/api/knowledge/reset', req => {
    const body = (req.body as { model?: string; project_id?: string })
    return store.mutate(state => {
      const before = state.knowledge.length
      if (body.model) state.knowledge = state.knowledge.filter(e => e.model !== body.model)
      else if (body.project_id) state.knowledge = state.knowledge.filter(e => e.project_id !== body.project_id)
      else state.knowledge = []
      return { status: `removed ${before - state.knowledge.length}` }
    })
  })
}

/**
 * Called by the queue and film mocks, so the offline UI fills from what the
 * user actually does there rather than only from the seed.
 */
export function recordMockEvent(state: MockState, partial: Partial<KnowledgeEvent>): void {
  const kind = partial.kind ?? 'generation_completed'
  const category = CATEGORY_OF[kind]
  if (!state.learning.enabled) return
  if (category && !state.learning[category]) return
  state.knowledge.push(event(partial))
}
