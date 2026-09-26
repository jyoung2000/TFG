/**
 * ShotSpec `layout3d` ↔ composer `CompositionScene`, the TypeScript twin of
 * `backend/film/scene_solver.py` (`composer_scene_from_layout` /
 * `layout_from_composition` / `camera_keyframes`). Same constants, same
 * conventions (metres, +Y up, camera looks down −Z, figures on y = 0), so a
 * scene built on either side round-trips within tolerance.
 */

import type { CameraMove, CompositionKeyframe, CompositionObject, CompositionScene, ShotFraming, Vec3 } from '../../../types/film'
import type { SpecLayout3D, SpecLayoutObject, SpecMotion } from '../../../types/shotspec'

export const FIGURE_REF_HEIGHT_M = 1.7
export const CHILD_MAX_M = 1.35
export const FEMALE_MAX_M = 1.72
export const DEFAULT_VFOV_DEG = 40

const vec = (values: number[], fill: number): Vec3 => [values[0] ?? fill, values[1] ?? fill, values[2] ?? fill]

export function figureVariantFor(heightM: number): 'male' | 'female' | 'child' {
  if (heightM < CHILD_MAX_M) return 'child'
  if (heightM < FEMALE_MAX_M) return 'female'
  return 'male'
}

export function cameraKeyframes(layout: SpecLayout3D, move: CameraMove, duration: number, intensity = 1): CompositionKeyframe[] {
  const pos = vec(layout.camera.pos, 0)
  const rot = vec(layout.camera.rot, 0)
  const subject = layout.objects.find(o => o.kind === 'figure') ?? layout.objects[0] ?? null
  let distance = 4
  if (subject) {
    const spos = vec(subject.pos, 0)
    distance = Math.max(0.5, Math.hypot(spos[0] - pos[0], spos[2] - pos[2]))
  }
  const clamped = Math.max(0.1, Math.min(3, intensity))
  const travel = distance * 0.25 * clamped
  const angle = (12 * Math.PI) / 180 * clamped
  const start: CompositionKeyframe = { id: 'kf-start', time: 0, transform: { position: pos, rotation: rot, scale: [1, 1, 1] }, fov: layout.camera.fov }
  if (move === 'static') return [start]
  const endPos: Vec3 = [...pos]
  const endRot: Vec3 = [...rot]
  switch (move) {
    case 'push_in':
    case 'follow':
      endPos[2] -= travel
      break
    case 'pull_out':
      endPos[2] += travel
      break
    case 'pan_left':
      endRot[1] += angle
      break
    case 'pan_right':
      endRot[1] -= angle
      break
    case 'tilt_up':
      endRot[0] += angle
      break
    case 'tilt_down':
      endRot[0] -= angle
      break
    case 'dolly_left':
      endPos[0] -= travel
      break
    case 'dolly_right':
      endPos[0] += travel
      break
    case 'orbit': {
      const spos = subject ? vec(subject.pos, 0) : ([0, 0, pos[2] - distance] as Vec3)
      const theta = (30 * Math.PI) / 180 * clamped
      const dx = pos[0] - spos[0]
      const dz = pos[2] - spos[2]
      endPos[0] = spos[0] + dx * Math.cos(theta) - dz * Math.sin(theta)
      endPos[2] = spos[2] + dx * Math.sin(theta) + dz * Math.cos(theta)
      endRot[1] = rot[1] + theta
      break
    }
  }
  return [start, { id: 'kf-end', time: Math.max(0.1, duration), transform: { position: endPos, rotation: endRot, scale: [1, 1, 1] }, fov: layout.camera.fov }]
}

const title = (text: string) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : '')

export function compositionFromLayout(layout: SpecLayout3D, options: { duration: number; move?: CameraMove; motion?: SpecMotion | null; framing?: ShotFraming | null; words?: Record<string, string> }): CompositionScene {
  const objects: CompositionObject[] = layout.objects.map(obj => {
    const pos = vec(obj.pos, 0)
    const rot = vec(obj.rot, 0)
    const scale = vec(obj.scale, 1)
    if (obj.kind === 'figure') {
      return {
        id: obj.id, name: title(obj.label || 'Figure'), type: 'figure', asset_id: null, visible: true, locked: false,
        transform: { position: pos, rotation: rot, scale: [scale[1], scale[1], scale[1]] },
        pose: {}, figure_variant: figureVariantFor(FIGURE_REF_HEIGHT_M * scale[1]), color: '', keyframes: [], fov: null,
      }
    }
    return {
      id: obj.id, name: title(obj.label || 'Prop'), type: 'cube', asset_id: null, visible: true, locked: false,
      transform: { position: pos, rotation: rot, scale }, pose: {}, figure_variant: 'male', color: '#8a93a6', keyframes: [], fov: null,
    }
  })
  const move = options.move ?? 'static'
  const intensity = options.motion?.magnitude ? Math.max(0.3, Math.min(2, options.motion.magnitude / 0.012)) : 1
  const camera: CompositionObject = {
    id: 'shot-camera', name: 'Shot Camera', type: 'camera', asset_id: null, visible: true, locked: false,
    transform: { position: vec(layout.camera.pos, 0), rotation: vec(layout.camera.rot, 0), scale: [1, 1, 1] },
    pose: {}, figure_variant: 'male', color: '#ffffff', keyframes: cameraKeyframes(layout, move, options.duration, intensity), fov: layout.camera.fov,
  }
  const framing: ShotFraming = {
    shot_size: 'medium', camera_angle: 'front', camera_elevation: 'eye', composition: 'center', fov_deg: layout.camera.fov,
    ots_foreground_id: null, ots_subject_id: null, ots_shoulder: 'left', camera_mode: 'manual',
    ...(options.framing ?? {}),
  }
  const words = options.words ?? {}
  if (words.shot_size) framing.shot_size = words.shot_size as ShotFraming['shot_size']
  if (words.angle) framing.camera_angle = words.angle as ShotFraming['camera_angle']
  if (words.height) framing.camera_elevation = words.height as ShotFraming['camera_elevation']
  framing.fov_deg = layout.camera.fov
  framing.camera_mode = 'manual'
  return { objects, camera, framing, camera_move: move, duration_seconds: Math.max(0.5, options.duration) }
}

export function layoutFromComposition(composition: CompositionScene, base?: SpecLayout3D | null): SpecLayout3D {
  const objects: SpecLayoutObject[] = []
  for (const obj of composition.objects) {
    if (obj.type === 'camera' || obj.visible === false) continue
    const t = obj.transform
    if (obj.type === 'figure') {
      objects.push({ id: obj.id, kind: 'figure', pos: [...t.position], rot: [...t.rotation], scale: [t.scale[1], t.scale[1], t.scale[1]], pose: 'stand', label: obj.name.toLowerCase() })
    } else {
      objects.push({ id: obj.id, kind: 'prop', pos: [...t.position], rot: [...t.rotation], scale: [...t.scale], pose: '', label: obj.name.toLowerCase() })
    }
  }
  const camera = composition.camera
    ? { pos: [...composition.camera.transform.position], rot: [...composition.camera.transform.rotation], fov: composition.camera.fov ?? composition.framing.fov_deg ?? DEFAULT_VFOV_DEG }
    : { pos: [0, 1.6, 4], rot: [0, 0, 0], fov: DEFAULT_VFOV_DEG }
  return { camera, objects, depth_map_path: base?.depth_map_path ?? '' }
}
