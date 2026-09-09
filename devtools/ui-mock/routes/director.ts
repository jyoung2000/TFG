/**
 * The AI Director, without a model behind it.
 *
 * With no provider configured this returns exactly what the backend returns —
 * the same `AI_DIRECTOR_KEY_MISSING` message and the same disabled state — so
 * the "connect a model" affordances can be worked on. Save any placeholder key
 * in Settings and the mock starts answering with structurally correct
 * responses (plan summary, tool results, context details) whose text says
 * plainly that it came from the mock, never from a model.
 */

import type {
  DirectorContextDetails,
  DirectorRole,
  DirectorStatus,
  FilmProject,
  FilmShot,
  OpenRouterModelInfo,
} from '../../../frontend/types/film'
import type { TextProviderId } from '../../../frontend/types/models'
import type { AppSettings } from '../../../frontend/types/settings'
import { MockHttpError, type Router } from '../http'
import type { MockState, Store } from '../state'

const KEY_MISSING =
  'AI_DIRECTOR_KEY_MISSING: connect a text model in Settings → API Keys — an OpenRouter, ' +
  'Claude, Grok or Gemini key, or a local OpenAI-compatible server for a fully offline ' +
  'director (or set the OPENROUTER_API_KEY environment variable)'

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: 'OpenRouter',
  anthropic: 'Claude (Anthropic)',
  xai: 'Grok (xAI)',
  gemini: 'Gemini (Google)',
  openai_compatible: 'Local / OpenAI-compatible',
}

const DEFAULT_MODELS: Record<string, string> = {
  openrouter: 'openai/gpt-4o-mini',
  anthropic: 'claude-sonnet-5',
  xai: 'grok-4',
  gemini: 'gemini-2.0-flash',
  openai_compatible: '',
}

const AUTO_ORDER: TextProviderId[] = ['openrouter', 'anthropic', 'xai', 'gemini', 'openai_compatible']

const ROLES: DirectorRole[] = ['script', 'storyboard', 'director', 'continuity', 'prompt_refinement']

/** Catalogs the model pickers can show without a network call. */
const MODEL_CATALOG: Record<string, string[]> = {
  openrouter: ['openai/gpt-4o-mini', 'anthropic/claude-sonnet-5', 'google/gemini-2.0-flash', 'meta-llama/llama-3.3-70b-instruct'],
  anthropic: ['claude-sonnet-5', 'claude-opus-5', 'claude-haiku-4-5-20251001'],
  xai: ['grok-4', 'grok-4-mini'],
  gemini: ['gemini-2.0-flash', 'gemini-2.0-pro'],
  openai_compatible: ['llama3.1:8b', 'qwen2.5:14b', 'mistral-nemo:12b'],
}

function configuration(state: MockState): Record<string, boolean> {
  const s = state.settings
  return {
    openrouter: s.hasOpenrouterApiKey,
    anthropic: s.hasAnthropicApiKey,
    xai: s.hasXaiApiKey,
    gemini: s.hasGeminiApiKey,
    openai_compatible: Boolean(s.openaiCompatibleBaseUrl.trim() && s.openaiCompatibleModel.trim()),
  }
}

function activeProvider(
  setting: AppSettings['directorProvider'],
  configured: Record<string, boolean>,
): TextProviderId | 'none' {
  if (setting !== 'auto') return configured[setting] ? setting : 'none'
  return AUTO_ORDER.find(id => configured[id]) ?? 'none'
}

function modelFor(settings: AppSettings, provider: string): string {
  switch (provider) {
    case 'openrouter':
      return settings.openrouterModels.director || settings.openrouterModels.defaultModel || DEFAULT_MODELS.openrouter
    case 'anthropic':
      return settings.anthropicModel || DEFAULT_MODELS.anthropic
    case 'xai':
      return settings.xaiModel || DEFAULT_MODELS.xai
    case 'gemini':
      return settings.geminiModel || DEFAULT_MODELS.gemini
    case 'openai_compatible':
      return settings.openaiCompatibleModel
    default:
      return ''
  }
}

/** The provider the mock would answer on, or a 400 that names the missing key. */
function requireProvider(state: MockState): { provider: string; model: string } {
  const configured = configuration(state)
  const setting = state.settings.directorProvider
  const active = activeProvider(setting, configured)
  if (active !== 'none') return { provider: active, model: modelFor(state.settings, active) }

  if (setting === 'openrouter') throw new MockHttpError(400, 'OPENROUTER_KEY_MISSING: OpenRouter is selected but no key is configured')
  if (setting === 'gemini') throw new MockHttpError(400, 'GEMINI_API_KEY_MISSING: Gemini is selected but no key is configured')
  if (setting === 'anthropic') throw new MockHttpError(400, 'ANTHROPIC_KEY_MISSING: Claude is selected but no key is configured')
  if (setting === 'xai') throw new MockHttpError(400, 'XAI_KEY_MISSING: Grok is selected but no key is configured')
  if (setting === 'openai_compatible') {
    throw new MockHttpError(400, 'OPENAI_COMPATIBLE_NOT_CONFIGURED: set the endpoint base URL and model in Settings → API Keys')
  }
  throw new MockHttpError(400, KEY_MISSING)
}

function context(provider: string, model: string, role: string, prompt: string, project: FilmProject | null): DirectorContextDetails {
  const summary = project ? JSON.stringify({ scenes: project.scenes.length, assets: project.assets.length }).length : 0
  return {
    provider,
    model,
    role,
    steps: 1,
    tool_calls: 0,
    prompt_chars: prompt.length,
    project_summary_chars: summary,
    prompt_tokens: null,
    completion_tokens: null,
    scope: project ? 'project' : 'chat',
  }
}

function modelList(provider: string): { models: OpenRouterModelInfo[]; fetched_at_ms: number; cached: boolean } {
  const ids = MODEL_CATALOG[provider] ?? []
  return {
    models: ids.map(id => ({
      id,
      name: id,
      context_length: 128000,
      prompt_price: '',
      completion_price: '',
      supports_tools: true,
      supports_json: true,
    })),
    fetched_at_ms: Date.now(),
    cached: false,
  }
}

function allShots(project: FilmProject): { sceneId: string; shot: FilmShot }[] {
  return project.scenes.flatMap(scene => scene.shots.map(shot => ({ sceneId: scene.id, shot })))
}

/**
 * A deliberately small instruction reader: enough to move real project state
 * so the storyboard visibly reacts, with no pretence of being a model.
 */
function interpret(project: FilmProject, instruction: string): { summary: string; changed: string[] } {
  const text = instruction.toLowerCase()
  const changed: string[] = []
  const shots = allShots(project)
  const numbered = text.match(/shot\s+(\d+)(?:\.(\d+))?/)
  let target = shots[0]
  if (numbered) {
    const scene = Number(numbered[1])
    const index = numbered[2] ? Number(numbered[2]) : 0
    target = numbered[2]
      ? (project.scenes[scene - 1]?.shots[index - 1] ?? shots[0]) && {
          sceneId: project.scenes[scene - 1]?.id ?? shots[0].sceneId,
          shot: project.scenes[scene - 1]?.shots[index - 1] ?? shots[0].shot,
        }
      : (shots[scene - 1] ?? shots[0])
  }
  if (!target) return { summary: 'Nothing to change — this film has no shots yet.', changed }

  const sizes = [
    ['extreme close', 'xcu'],
    ['close-up', 'closeup'],
    ['closeup', 'closeup'],
    ['medium', 'medium'],
    ['wide', 'wide'],
    ['full', 'full'],
  ] as const
  for (const [phrase, size] of sizes) {
    if (text.includes(phrase)) {
      target.shot.framing.shot_size = size
      changed.push(`set_shot_size(${target.shot.id}, ${size})`)
      break
    }
  }
  if (text.includes('over the shoulder') || text.includes('ots')) {
    target.shot.framing.camera_angle = 'ots'
    target.shot.framing.ots_shoulder = text.includes('left') ? 'left' : 'right'
    changed.push(`set_camera_angle(${target.shot.id}, ots)`)
  }
  if (text.includes('push in') || text.includes('push-in')) {
    target.shot.camera_move = 'push_in'
    changed.push(`set_camera_move(${target.shot.id}, push_in)`)
  }
  const seconds = text.match(/(\d+)\s*(?:second|sec|s)\b/)
  if (seconds) {
    target.shot.duration_seconds = Number(seconds[1])
    changed.push(`set_duration(${target.shot.id}, ${seconds[1]}s)`)
  }
  target.shot.updated_at = Date.now()

  return {
    summary: changed.length
      ? `Applied ${changed.length} change${changed.length === 1 ? '' : 's'} to ${target.shot.title}.`
      : `No change matched "${instruction}". The UI-only director understands shot size, OTS, push-in and durations.`,
    changed,
  }
}

const MOCK_NOTE = '(UI-only mode: this reply comes from the mock backend, not from a model.)'

export function registerDirectorRoutes(router: Router, store: Store): void {
  router.get('/api/film/director/status', (): DirectorStatus => {
    const state = store.data
    const configured = configuration(state)
    const active = activeProvider(state.settings.directorProvider, configured)
    const setting = state.settings.directorProvider

    let message = ''
    if (active === 'none') {
      message =
        setting !== 'auto' && !configured[setting]
          ? `${PROVIDER_LABELS[setting] ?? setting} is selected but not configured yet.`
          : KEY_MISSING
    }

    const status: DirectorStatus = {
      provider_setting: setting,
      active_provider: active,
      gemini_configured: configured.gemini,
      openrouter_configured: configured.openrouter,
      openai_compatible_configured: configured.openai_compatible,
      anthropic_configured: configured.anthropic,
      xai_configured: configured.xai,
      openrouter_key_source: state.settings.hasOpenrouterApiKey ? 'settings' : 'none',
      roles: ROLES.map(role => ({
        role,
        provider: active === 'none' ? 'none' : active,
        model: active === 'none' ? '' : modelFor(state.settings, active),
      })),
      tools: [
        { name: 'set_shot_type', description: 'Change a shot’s size, angle or elevation' },
        { name: 'set_camera_move', description: 'Change the camera move' },
        { name: 'set_ots', description: 'Make a shot over-the-shoulder' },
        { name: 'position_object', description: 'Move a figure or prop in the composition' },
        { name: 'generate_preview', description: 'Queue a preview render' },
      ],
      providers: AUTO_ORDER.map(id => ({
        id,
        label: PROVIDER_LABELS[id],
        configured: configured[id],
        model: modelFor(state.settings, id),
        needs_key: id !== 'openai_compatible',
        note: id === 'openai_compatible' ? 'Runs fully offline against a local server' : '',
      })),
      message,
    }
    return status
  })

  router.get('/api/film/director/models/:provider', req => modelList(req.params.provider))
  router.get('/api/film/director/openrouter/models', () => modelList('openrouter'))
  router.get('/api/film/director/openai-compatible/models', () => modelList('openai_compatible'))

  router.post('/api/film/director/openrouter/validate', () => {
    const state = store.data
    if (!state.settings.hasOpenrouterApiKey) {
      throw new MockHttpError(400, 'OPENROUTER_KEY_MISSING: OpenRouter is selected but no key is configured')
    }
    return {
      valid: true,
      label: 'UI-only mock key',
      usage: 0,
      limit: null,
      is_free_tier: true,
      message: 'Accepted by the mock backend — no request left this machine.',
    }
  })

  router.post('/api/film/director/chat', req => {
    const { provider, model } = requireProvider(store.data)
    const messages = Array.isArray(req.body.messages) ? (req.body.messages as { content?: string }[]) : []
    const last = String(messages[messages.length - 1]?.content ?? '')
    const role = String(req.body.role ?? 'prompt_refinement')
    return {
      reply: `${MOCK_NOTE} You asked: “${last.slice(0, 160)}”. In the full app a ${PROVIDER_LABELS[provider]} model would answer here.`,
      suggested_prompt: last
        ? `${last.trim()}, anamorphic 35mm, shallow depth of field, volumetric light, cinematic colour grade`
        : '',
      suggested_negative_prompt: 'text, watermark, logo, distorted hands',
      suggested_duration_seconds: null,
      context: context(provider, model, role, last, null),
    }
  })

  router.post('/api/film/projects/:projectId/director/instruct', req =>
    store.mutate(() => {
      const { provider, model } = requireProvider(store.data)
      const project = store.ensureProject(req.params.projectId)
      const instruction = String(req.body.instruction ?? '')
      const { summary, changed } = interpret(project, instruction)
      project.updated_at = Date.now()
      return {
        plan_summary: summary,
        results: changed.map(name => ({ name, ok: true, result: 'applied', error: '' })),
        reply: `${summary} ${MOCK_NOTE}`,
        context: { ...context(provider, model, 'director', instruction, project), tool_calls: changed.length },
      }
    }),
  )

  router.post('/api/film/projects/:projectId/director/command', req =>
    store.mutate(() => {
      const project = store.ensureProject(req.params.projectId)
      const name = String(req.body.name ?? '')
      const { changed } = interpret(project, name)
      return {
        results: [{ name, ok: changed.length > 0, result: changed, error: changed.length ? '' : 'No effect in UI-only mode' }],
      }
    }),
  )

  router.post('/api/film/projects/:projectId/scenes/:sceneId/shots/:shotId/refine-prompt', req =>
    store.mutate(() => {
      const { provider, model } = requireProvider(store.data)
      const project = store.ensureProject(req.params.projectId)
      const scene = project.scenes.find(s => s.id === req.params.sceneId)
      const shot = scene?.shots.find(s => s.id === req.params.shotId)
      if (!shot) throw new MockHttpError(404, `Shot not found: ${req.params.shotId}`)
      const previous = shot.visual_prompt
      const guidance = String(req.body.guidance ?? '')
      shot.visual_prompt =
        `${previous || shot.title}${guidance ? `, ${guidance}` : ''}, ` +
        'anamorphic 35mm, practical halation, volumetric haze, restrained colour grade'
      shot.prompt_locked = true
      shot.updated_at = Date.now()
      project.updated_at = Date.now()
      return { shot, previous_prompt: previous, context: context(provider, model, 'prompt_refinement', guidance, project) }
    }),
  )
}
