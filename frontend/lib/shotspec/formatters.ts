/**
 * Client-side prompt preview from a ShotSpec.
 *
 * A faithful-enough mirror of `compile_from_spec` for instant feedback while
 * the user edits blocks; the backend result is authoritative and replaces
 * the preview when it arrives. Formatter shapes after macchant/imex-next
 * `synthesize.ts` (MIT).
 */

import type { PromptStyle, ShotSpec } from '../../types/shotspec'
import { topTags } from './schema'

const SHOT_SIZE: Record<string, string> = {
  xwide: 'extreme wide shot', wide: 'wide shot', full: 'full shot', medium: 'medium shot', mcu: 'medium close-up', closeup: 'close-up', xcu: 'extreme close-up',
}
const ANGLE: Record<string, string> = {
  front: 'front angle', threeQuarterLeft: 'three-quarter left angle', threeQuarterRight: 'three-quarter right angle', profile: 'profile angle', back: 'shot from behind', ots: 'over-the-shoulder shot', pov: 'point-of-view shot', dutch: 'dutch angle, tilted horizon',
}
const HEIGHT: Record<string, string> = {
  eye: 'eye-level camera', low: 'low-angle camera looking up', high: 'high-angle camera looking down', bird: "bird's-eye view from above", worm: "worm's-eye view from ground level",
}
const MOVE: Record<string, string> = {
  static: 'static camera, locked-off shot', push_in: 'slow push in, camera moving toward the subject', pull_out: 'slow pull out, camera moving away from the subject', pan_left: 'camera panning left', pan_right: 'camera panning right', tilt_up: 'camera tilting up', tilt_down: 'camera tilting down', dolly_left: 'camera trucking left, lateral movement', dolly_right: 'camera trucking right, lateral movement', orbit: 'camera orbiting around the subject', follow: 'camera following the subject',
}
const DEFAULT_NEGATIVES = ['text', 'watermark', 'logo', 'distorted hands', 'extra limbs', 'blurry']

export interface Sections {
  subjects: string
  action: string
  location: string
  shot_size: string
  camera: string
  lens: string
  movement: string
  lighting: string
  style: string
  timeline: string
}

const join = (parts: (string | undefined)[], sep = ', ') => parts.map(p => (p ?? '').trim()).filter(Boolean).join(sep)

export function sectionsOf(spec: ShotSpec, still: boolean): Sections {
  const subjects = spec.subjects.map(s => {
    const label = s.count > 1 ? `${s.count} ${s.label}` : s.label
    return s.attributes.length ? `${label} (${s.attributes.join(', ')})` : label
  }).join('; ')
  const scene = spec.scene
  let location = join([scene.location, scene.environment, scene.time_of_day, scene.weather])
  const layers = join([scene.fg && `foreground: ${scene.fg}`, scene.mg && `midground: ${scene.mg}`, scene.bg && `background: ${scene.bg}`], '; ')
  if (layers) location = location ? `${location}. ${layers}` : layers
  const cam = spec.camera
  const camera = join([ANGLE[cam.angle] ?? cam.angle, HEIGHT[cam.height] ?? (cam.height && `${cam.height} camera height`)])
  const lens = join([
    cam.lens_estimate,
    cam.focal_mm ? `${Math.round(cam.focal_mm)}mm lens` : '',
    cam.aperture,
    cam.dof && `${cam.dof} depth of field`,
    cam.focus && `focus on ${cam.focus}`,
  ])
  let movement = still ? '' : MOVE[cam.move] ?? cam.move
  if (movement && cam.move !== 'static') {
    const intensity = cam.move_intensity < 0.3 ? 'subtle' : cam.move_intensity < 0.7 ? 'steady' : 'fast'
    movement = `${intensity} ${movement}`
  }
  if (!still && cam.handheld) movement = movement ? `${movement}, handheld` : 'handheld camera'
  const light = spec.lighting
  const lighting = join([
    light.quality && `${light.quality} light`,
    light.key_direction && `key light from the ${light.key_direction}`,
    light.color_temp && `${light.color_temp} colour temperature`,
    light.mood && `${light.mood} mood`,
  ])
  const styleParts = [spec.style.medium === 'photo' ? 'photograph' : spec.style.medium, ...topTags(spec, 8), ...spec.style.artists.slice(0, 1).map(a => `in the style of ${a}`)]
  const palette = spec.measured.palette.slice(0, 3).map(p => p.hex).join(', ')
  if (palette) styleParts.push(`palette of ${palette}`)
  const style = join([...new Set(styleParts.filter(Boolean))])
  let timeline = ''
  if (!still && spec.source.kind === 'video_shot' && spec.source.start !== null && spec.source.end !== null) {
    timeline = `${Math.max(0.5, spec.source.end - spec.source.start).toFixed(1)} second shot`
    if (spec.motion.pacing) timeline += `, ${spec.motion.pacing} pacing`
  }
  return { subjects, action: spec.narrative.what_happens, location, shot_size: SHOT_SIZE[cam.shot_size] ?? cam.shot_size, camera, lens, movement, lighting, style, timeline }
}

export function negativesOf(spec: ShotSpec): string {
  return [...new Set([...spec.style.negatives, ...DEFAULT_NEGATIVES])].join(', ')
}

const STILL_TARGETS = new Set(['z_image', 'qwen_image_edit', 'flux', 'sdxl'])

export function isStillTarget(target: string): boolean {
  return STILL_TARGETS.has(target)
}

function narrative(s: Sections): string {
  const opening = join([s.shot_size, s.subjects], '. ')
  const body = join([opening, s.action, s.location, join([s.camera, s.lens, s.movement]), join([s.lighting, s.style]), s.timeline], '. ')
  return body && !body.endsWith('.') ? `${body}.` : body
}

function structured(s: Sections): string {
  const rows: [string, string][] = [
    ['Subject', join([s.subjects, s.action])],
    ['Scene', s.location],
    ['Framing', join([s.shot_size, s.camera, s.lens])],
    ['Motion', s.movement],
    ['Light', s.lighting],
    ['Style', s.style],
    ['Timing', s.timeline],
  ]
  return rows.filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join('. ')
}

function tagged(s: Sections): string {
  return join([s.shot_size, s.subjects, s.action, s.location, s.camera, s.lens, s.lighting, s.style])
}

function weighted(s: Sections): string {
  const w = (term: string, weight: number) => (!term ? '' : weight === 1 ? term : `(${term}:${weight.toFixed(1)})`)
  return join([w(s.subjects, 1.2), w(s.action, 1.1), w(s.shot_size, 1.1), w(s.location, 1), w(s.camera, 1), w(s.lens, 1), w(s.lighting, 1), w(s.style, 1.1)])
}

function jsonStyle(s: Sections): string {
  return JSON.stringify(Object.fromEntries(Object.entries(s).filter(([, v]) => v)))
}

/** Preview a prompt for a target and style; the server result is authoritative. */
export function previewPrompt(spec: ShotSpec, target: string, style: PromptStyle, hints: string[] = []): { prompt: string; negative_prompt: string } {
  const sections = sectionsOf(spec, isStillTarget(target))
  if (hints.length) {
    const extra = hints.filter(h => h && !sections.style.toLowerCase().includes(h.toLowerCase()))
    if (extra.length) sections.style = join([sections.style, ...extra])
  }
  const negative = negativesOf(spec)
  switch (style) {
    case 'narrative':
      return { prompt: narrative(sections), negative_prompt: negative }
    case 'structured':
      return { prompt: structured(sections), negative_prompt: negative }
    case 'tagged':
      return { prompt: tagged(sections), negative_prompt: negative }
    case 'weighted':
      return { prompt: weighted(sections), negative_prompt: negative }
    case 'json':
      return { prompt: jsonStyle(sections), negative_prompt: negative }
    case 'negative_only':
      return { prompt: '', negative_prompt: negative }
  }
}
