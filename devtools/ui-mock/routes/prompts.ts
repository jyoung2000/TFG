/**
 * The model-specific prompt compiler, simulated.
 *
 * The rules are the real ones, restated: same targets, same styles, same
 * budgets, same "nothing is lost silently". A prompt that reads as tailored in
 * the offline UI reads the same way in the app, and an unrecognised model is
 * flagged in both.
 */

import type {
  CompiledPrompt,
  CompilePromptResponse,
  ConventionBasis,
  PromptStyle,
  PromptTarget,
  ShotBrief,
} from '../../../frontend/types/prompts'
import { EMPTY_BRIEF } from '../../../frontend/types/prompts'
import { MockHttpError, type Router } from '../http'
import type { Store } from '../state'

interface Target extends PromptTarget {
  renders_audio: boolean
  renders_motion: boolean
}

const GENERIC: Target = {
  id: 'generic',
  label: 'General video model',
  style: 'narrative',
  basis: 'tfg_default',
  note:
    'Not a model this app has a convention for, so the general one is used: plain descriptive ' +
    'language, action first. Check the model’s own prompt guidance before relying on the result.',
  max_chars: 1000,
  supports_negative: true,
  renders_audio: false,
  renders_motion: true,
  matches: [],
}

const TARGETS: Target[] = [
  {
    id: 'ltx', label: 'LTX Video', style: 'narrative', basis: 'publisher_guidance',
    note: 'LTX’s own prompting guidance asks for a single chronological paragraph that describes the motion as it happens, rather than a list of tags.',
    max_chars: 1500, supports_negative: true, renders_audio: false, renders_motion: true,
    matches: ['ltx', 'lightricks', 'ltxv'],
  },
  {
    id: 'wan', label: 'Wan', style: 'structured', basis: 'publisher_guidance',
    note: 'Wan’s prompt guide describes prompts as subject, then scene, then motion, then aesthetic direction.',
    max_chars: 900, supports_negative: true, renders_audio: false, renders_motion: true,
    matches: ['wan2', 'wan-2', 'wan_2', 'wanx'],
  },
  {
    id: 'hunyuan', label: 'HunyuanVideo', style: 'narrative', basis: 'community_convention',
    note: 'Descriptive sentences rather than tags, kept short. No published house style, so this is the convention in common use.',
    max_chars: 800, supports_negative: true, renders_audio: false, renders_motion: true,
    matches: ['hunyuan'],
  },
  {
    id: 'flux', label: 'FLUX (stills)', style: 'narrative', basis: 'publisher_guidance',
    note: 'FLUX is guided toward natural-language descriptions rather than tag lists. A still, so motion and timeline are dropped.',
    max_chars: 700, supports_negative: false, renders_audio: false, renders_motion: false,
    matches: ['flux'],
  },
  {
    id: 'sdxl', label: 'SDXL-family checkpoints (stills)', style: 'tagged', basis: 'community_convention',
    note: 'Tag-trained checkpoints respond to comma-separated descriptors with the most important first.',
    max_chars: 600, supports_negative: true, renders_audio: false, renders_motion: false,
    matches: ['sdxl', 'stable-diffusion', 'sd15', 'sd-1.5', 'juggernaut', 'z_image', 'z-image'],
  },
  {
    id: 'veo', label: 'Veo-style hosted video', style: 'narrative', basis: 'community_convention',
    note: 'Hosted models in this family take a descriptive paragraph and generate sound with the picture.',
    max_chars: 1000, supports_negative: false, renders_audio: true, renders_motion: true,
    matches: ['veo', 'sora', 'kling', 'minimax', 'hailuo', 'pika', 'runway', 'seedance'],
  },
]

/**
 * Mirrors `backend/film/shot_vocabulary.py`. The storyboard stores enum keys
 * ("xwide", "push_in"); the compiler needs the phrases they stand for, or the
 * offline UI shows "xwide." where the app shows "extreme wide shot".
 */
const SHOT_SIZE_PHRASES: Record<string, string> = {
  xwide: 'extreme wide shot', wide: 'wide shot', full: 'full shot', medium: 'medium shot',
  mcu: 'medium close-up', closeup: 'close-up', xcu: 'extreme close-up',
}
const ANGLE_PHRASES: Record<string, string> = {
  front: 'front angle', threeQuarterLeft: 'three-quarter left angle',
  threeQuarterRight: 'three-quarter right angle', profile: 'profile angle',
  back: 'shot from behind', ots: 'over-the-shoulder shot', pov: 'point-of-view shot',
  dutch: 'dutch angle, tilted horizon',
}
const ELEVATION_PHRASES: Record<string, string> = {
  eye: 'eye-level camera', low: 'low-angle camera looking up', high: 'high-angle camera looking down',
  bird: "bird's-eye view from above", worm: "worm's-eye view from ground level",
}
const COMPOSITION_PHRASES: Record<string, string> = {
  center: 'subject centered in frame', leftThird: 'subject on the left third of the frame',
  rightThird: 'subject on the right third of the frame', upperThird: 'subject in the upper third of the frame',
  lowerThird: 'subject in the lower third of the frame',
  negativeSpace: 'strong negative space, subject far off-center',
  symmetrical: 'symmetrical composition', leadingLines: 'leading lines drawing the eye to the subject',
}
const CAMERA_MOVE_PHRASES: Record<string, string> = {
  static: 'static camera, locked-off shot', push_in: 'slow push in, camera moving toward the subject',
  pull_out: 'slow pull out, camera moving away from the subject', pan_left: 'camera panning left',
  pan_right: 'camera panning right', tilt_up: 'camera tilting up', tilt_down: 'camera tilting down',
  dolly_left: 'camera trucking left, lateral movement', dolly_right: 'camera trucking right, lateral movement',
  orbit: 'camera orbiting around the subject', follow: 'camera following the subject',
}

const SACRIFICE_ORDER = ['style', 'lens', 'timeline', 'lighting', 'camera', 'location']

function resolveTarget(modelId: string): [Target, boolean] {
  const needle = (modelId || '').toLowerCase()
  if (!needle) return [GENERIC, false]
  const found = TARGETS.find(target => target.matches.some(fragment => needle.includes(fragment)))
  return found ? [found, true] : [GENERIC, false]
}

const clean = (text: string) => text.trim().replace(/\.$/, '').trim()
/** Join prose fragments without leaving "…in snow., Cramped interior" behind. */
const clauses = (...parts: (string | undefined)[]) => parts.map(p => clean(p ?? '')).filter(Boolean).join(', ')
const join = (parts: string[], separator = '. ') => parts.map(p => p.trim()).filter(Boolean).join(separator)

function sections(brief: ShotBrief, target: Target): [Record<string, string>, string[]] {
  const dropped: string[] = []
  const still = !target.renders_motion
  const out: Record<string, string> = {}

  // `scene_intent` is deliberately absent: it says what the shot is for, which
  // no render model can act on.
  if (brief.subjects.length) out.subjects = brief.subjects.map(clean).filter(Boolean).join('; ')
  for (const key of ['action', 'location', 'shot_size', 'camera', 'lens'] as const) {
    if (brief[key]) out[key] = clean(brief[key])
  }
  if (brief.movement) {
    if (still) dropped.push(`movement — ${target.label} renders a still frame`)
    else out.movement = clean(brief.movement)
  }
  if (brief.lighting) out.lighting = clean(brief.lighting)
  if (brief.style) out.style = clean(brief.style)
  if (brief.audio) {
    if (target.renders_audio) out.audio = clean(brief.audio)
    else dropped.push(`audio — ${target.label} renders no sound`)
  }
  if (brief.timeline) {
    if (still) dropped.push(`timeline — ${target.label} renders a still frame`)
    else out.timeline = clean(brief.timeline)
  }
  if (brief.continuity.length) out.continuity = brief.continuity.map(clean).filter(Boolean).join('; ')

  return [Object.fromEntries(Object.entries(out).filter(([, v]) => v)), dropped]
}

function render(style: PromptStyle, s: Record<string, string>): string {
  if (style === 'structured') {
    const ordered: [string, string][] = [
      ['Subject', join([s.subjects ?? '', s.action ?? ''], ', ')],
      ['Scene', s.location ?? ''],
      ['Framing', join([s.shot_size ?? '', s.camera ?? '', s.lens ?? ''], ', ')],
      ['Motion', s.movement ?? ''],
      ['Light', s.lighting ?? ''],
      ['Style', s.style ?? ''],
      ['Audio', s.audio ?? ''],
      ['Timing', s.timeline ?? ''],
      ['Continuity', s.continuity ?? ''],
    ]
    return join(ordered.filter(([, v]) => v).map(([label, v]) => `${label}: ${v}`), '. ')
  }
  if (style === 'tagged') {
    return [s.shot_size, s.subjects, s.action, s.location, s.camera, s.lens, s.lighting, s.style, s.continuity]
      .filter(Boolean)
      .join(', ')
  }
  const body = join([
    join([s.shot_size ?? '', s.subjects ?? ''], '. '),
    s.action ?? '',
    s.location ?? '',
    join([s.camera ?? '', s.lens ?? '', s.movement ?? ''], ', '),
    join([s.lighting ?? '', s.style ?? ''], ', '),
    s.audio ?? '',
    s.timeline ?? '',
  ], '. ')
  const withContinuity = s.continuity
    ? body ? `${body}. Must match: ${s.continuity}` : `Must match: ${s.continuity}`
    : body
  return withContinuity && !withContinuity.endsWith('.') ? `${withContinuity}.` : withContinuity
}

export function compilePrompt(brief: ShotBrief, modelId: string): CompiledPrompt {
  const [target, matched] = resolveTarget(modelId)
  const [parts, dropped] = sections(brief, target)

  let text = render(target.style, parts)
  for (const key of SACRIFICE_ORDER) {
    if (text.length <= target.max_chars) break
    if (!(key in parts)) continue
    delete parts[key]
    dropped.push(`${key.replace(/_/g, ' ')} — over the ${target.max_chars}-character budget for ${target.label}`)
    text = render(target.style, parts)
  }
  if (text.length > target.max_chars) {
    const cut = text.lastIndexOf('. ', target.max_chars)
    text = (cut > 0 ? text.slice(0, cut + 1) : text.slice(0, target.max_chars)).trimEnd()
    dropped.push(`trailing detail — trimmed to ${target.label}’s ${target.max_chars}-character budget`)
  }

  let negative = ''
  if (brief.negative.length) {
    if (target.supports_negative) negative = brief.negative.map(clean).filter(Boolean).join(', ')
    else dropped.push(`negative constraints — ${target.label} takes no negative prompt`)
  }

  return {
    model: modelId,
    target_id: target.id,
    target_label: target.label,
    style: target.style,
    basis: target.basis as ConventionBasis,
    note: target.note,
    prompt: text,
    negative_prompt: negative,
    matched,
    dropped,
  }
}

/** A brief from the demo film's own shot fields, rather than a canned string. */
function briefFromShot(store: Store, projectId: string, shotId: string): ShotBrief {
  const project = store.project(projectId)
  const scene = project?.scenes.find(s => s.shots.some(shot => shot.id === shotId))
  const shot = scene?.shots.find(s => s.id === shotId)
  if (!project || !scene || !shot) throw new MockHttpError(404, `Shot not found: ${shotId}`)

  const character = shot.characters
    .map(c => project.assets.find(a => a.id === c.asset_id))
    .filter((a): a is NonNullable<typeof a> => Boolean(a))
  const location = project.assets.find(a => a.id === (shot.location_id || scene.location_id))

  return {
    ...EMPTY_BRIEF,
    scene_intent: scene.description,
    subjects: character.map(a => clauses(a.name, a.description, a.wardrobe)),
    action: shot.action || shot.description,
    location: location ? clauses(location.name, location.description, location.environment) : clean(scene.description),
    shot_size: SHOT_SIZE_PHRASES[shot.framing.shot_size] ?? '',
    camera: [
      ANGLE_PHRASES[shot.framing.camera_angle],
      ELEVATION_PHRASES[shot.framing.camera_elevation],
      COMPOSITION_PHRASES[shot.framing.composition],
    ].filter(Boolean).join(', '),
    movement: CAMERA_MOVE_PHRASES[shot.camera_move] ?? '',
    lighting: [scene.lighting, scene.time_of_day].filter(Boolean).join(', '),
    style: [project.settings.style_prompt, scene.mood && `${scene.mood} mood`].filter(Boolean).join(', '),
    audio: shot.dialogue ? `dialogue: "${shot.dialogue}"` : '',
    timeline: `${shot.duration_seconds}s at ${shot.generation.fps}fps`,
    continuity: character.filter(a => a.wardrobe).map(a => `${a.name} wearing ${a.wardrobe}`),
    negative: (shot.negative_prompt || project.settings.default_negative_prompt)
      .split(',')
      .map(s => s.trim())
      .filter(Boolean),
  }
}

function briefFromAnalysis(store: Store, analysisId: string, shotId: string): ShotBrief {
  const analysis = store.data.analyses[analysisId]
  const shot = analysis?.shots.find(s => s.id === shotId)
  if (!analysis || !shot) throw new MockHttpError(404, `Analysed shot not found: ${shotId}`)
  return {
    ...EMPTY_BRIEF,
    scene_intent: shot.narrative.narrative_purpose || shot.narrative.story_beat,
    subjects: shot.visual.subjects.slice(0, 4),
    action: shot.narrative.what_happens || shot.visual.description,
    location: [shot.visual.location, shot.visual.environment].filter(Boolean).join(' ').trim(),
    shot_size: shot.visual.shot_size,
    camera: [shot.visual.angle, shot.visual.camera_height, shot.cinematography.camera_position].filter(Boolean).join(', '),
    lens: [shot.visual.lens_estimate, shot.visual.depth_of_field].filter(Boolean).join(', '),
    movement: shot.cinematography.camera_movement || (shot.cinematography.is_static ? 'static camera' : ''),
    lighting: [shot.visual.lighting, shot.visual.palette.slice(0, 3).join(', '), shot.visual.contrast].filter(Boolean).join(', '),
    style: [shot.visual.visual_style, shot.visual.production_design, analysis.visual_style].filter(Boolean).join(', '),
    audio: shot.audio.analyzed ? [shot.audio.dialogue, shot.audio.ambience, shot.audio.music].filter(Boolean).join('; ') : '',
    timeline: [`${shot.duration.toFixed(1)} seconds`, shot.editorial.rhythm || shot.narrative.pacing]
      .filter(Boolean)
      .map((part, index) => (index === 1 ? `${part} pacing` : part))
      .join(', '),
    continuity: shot.narrative.continuity_implications.slice(0, 4),
    negative: ['text', 'watermark', 'logo', 'distorted hands', 'extra limbs'],
  }
}

export function registerPromptRoutes(router: Router, store: Store): void {
  router.get('/api/prompts/targets', () => ({ targets: [...TARGETS, GENERIC] }))

  router.post('/api/prompts/compile', (req): CompilePromptResponse => {
    const body = req.body as {
      models?: string[]
      brief?: ShotBrief
      project_id?: string
      scene_id?: string
      shot_id?: string
      analysis_id?: string
      analysis_shot_id?: string
    }
    const sources = [
      Boolean(body.brief),
      Boolean(body.project_id && body.shot_id),
      Boolean(body.analysis_id && body.analysis_shot_id),
    ].filter(Boolean).length
    if (sources !== 1) {
      throw new MockHttpError(
        400,
        'Name exactly one source: a brief, a project shot (project_id + scene_id + shot_id), ' +
          'or an analysed shot (analysis_id + analysis_shot_id).',
      )
    }

    const brief = body.brief
      ? { ...EMPTY_BRIEF, ...body.brief }
      : body.project_id
        ? briefFromShot(store, body.project_id, body.shot_id ?? '')
        : briefFromAnalysis(store, body.analysis_id ?? '', body.analysis_shot_id ?? '')

    const seen = new Set<string>()
    const prompts: CompiledPrompt[] = []
    for (const model of body.models ?? []) {
      const key = model.trim()
      if (!key || seen.has(key)) continue
      seen.add(key)
      prompts.push(compilePrompt(brief, key))
    }
    return { brief, prompts }
  })
}
