/**
 * ShotSpec helpers for the renderer: an empty spec, section labels, lock
 * toggles and the same `section.field=value` keys the backend learns on.
 * (Design after macchant/imex-next `types/schema.ts`, MIT.)
 */

import { SPEC_SECTIONS, type ShotSpec, type SpecSection } from '../../types/shotspec'

export const SECTION_LABEL: Record<SpecSection, string> = {
  measured: 'Measured',
  subjects: 'Subjects',
  scene: 'Scene',
  camera: 'Camera',
  lighting: 'Lighting',
  style: 'Style',
  motion: 'Motion',
  layout3d: '3D layout',
  narrative: 'Narrative',
}

export const PROVENANCE_LABEL: Record<string, string> = {
  measured: 'measured',
  florence: 'detected (Florence-2)',
  clip: 'ranked (CLIP)',
  depth: 'depth',
  flow: 'optical flow',
  vlm: 'language model',
  user: 'you',
  '': 'empty',
}

export function emptySpec(kind: 'image' | 'video_shot' = 'image'): ShotSpec {
  return {
    version: 1,
    source: { kind, hash: '', path: '', width: 0, height: 0, aspect: '', fps: null, start: null, end: null },
    measured: { palette: [], luminance: 0, contrast: 0, saturation: 0, edge_density: 0, sharpness: 0, exif: {} },
    subjects: [],
    scene: { location: '', environment: '', time_of_day: '', weather: '', fg: '', mg: '', bg: '' },
    camera: { shot_size: '', angle: '', height: '', fov_deg: null, focal_mm: null, lens_estimate: '', aperture: '', dof: '', focus: '', move: '', move_intensity: 0, handheld: false, roll: 0 },
    lighting: { key_direction: '', quality: '', color_temp: '', mood: '' },
    style: { tags: [], medium: '', artists: [], negatives: [] },
    motion: { dominant: { pan: 0, tilt: 0, zoom: 0, roll: 0 }, magnitude: 0, subject_motion: 0, pacing: '' },
    layout3d: { camera: { pos: [0, 1.6, 4], rot: [0, 0, 0], fov: 40 }, objects: [], depth_map_path: '' },
    narrative: { what_happens: '', purpose: '', beat: '' },
    confidence: {},
    provenance: {},
    locks: {},
  }
}

export function isLocked(spec: ShotSpec, section: SpecSection): boolean {
  return Boolean(spec.locks[section])
}

export function toggleLock(spec: ShotSpec, section: SpecSection): ShotSpec {
  return { ...spec, locks: { ...spec.locks, [section]: !spec.locks[section] } }
}

/** Replace one section with the user's edit; it becomes locked and `user`-owned. */
export function editSection<K extends SpecSection>(spec: ShotSpec, section: K, value: ShotSpec[K], lock = true): ShotSpec {
  return {
    ...spec,
    [section]: value,
    provenance: { ...spec.provenance, [section]: 'user' },
    confidence: { ...spec.confidence, [section]: 1 },
    locks: lock ? { ...spec.locks, [section]: true } : spec.locks,
  }
}

function slug(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, ' ').split(/\s+/).join('-').slice(0, 40)
}

export function topTags(spec: ShotSpec, limit = 8): string[] {
  return [...spec.style.tags].sort((a, b) => b.score - a.score).slice(0, limit).map(t => t.term)
}

/** Same keys as `ShotSpec.attribute_keys()` on the backend. */
export function attributeKeys(spec: ShotSpec): string[] {
  const keys = new Set<string>()
  for (const field of ['shot_size', 'angle', 'height', 'move', 'dof', 'lens_estimate'] as const) {
    const value = spec.camera[field]
    if (value) keys.add(`camera.${field}=${slug(String(value))}`)
  }
  for (const field of ['quality', 'key_direction', 'color_temp', 'mood'] as const) {
    const value = spec.lighting[field]
    if (value) keys.add(`lighting.${field}=${slug(value)}`)
  }
  if (spec.style.medium) keys.add(`style.medium=${slug(spec.style.medium)}`)
  for (const term of topTags(spec, 4)) keys.add(`style.tag=${slug(term)}`)
  if (spec.scene.time_of_day) keys.add(`scene.time_of_day=${slug(spec.scene.time_of_day)}`)
  if (spec.source.aspect) keys.add(`source.aspect=${spec.source.aspect}`)
  if (spec.motion.pacing) keys.add(`motion.pacing=${slug(spec.motion.pacing)}`)
  const count = spec.subjects.reduce((sum, s) => sum + s.count, 0)
  if (count) keys.add(`subjects.count=${Math.min(count, 5)}`)
  return [...keys].sort()
}

export function sectionsWithContent(spec: ShotSpec): SpecSection[] {
  return SPEC_SECTIONS.filter(section => {
    const value = spec[section]
    if (Array.isArray(value)) return value.length > 0
    return Object.values(value as unknown as Record<string, unknown>).some(v => (Array.isArray(v) ? v.length > 0 : typeof v === 'object' && v !== null ? Object.values(v as Record<string, unknown>).some(Boolean) : Boolean(v)))
  })
}
