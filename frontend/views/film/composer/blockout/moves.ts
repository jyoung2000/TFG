/**
 * Bridge between the composer's camera moves and Blockout's move library.
 *
 * The 39 presets in `engine/camera-moves.ts` (wassermanproductions/blockout,
 * Apache-2.0 — NOTICE in this folder) generate `CameraMarkSpec`s in Blockout's
 * conventions (pan/tilt/roll radians, +X right, −Z forward, heading 0 faces
 * −Z). This module runs a preset against the composer's subject and camera and
 * converts the marks into `CompositionKeyframe`s (three.js Euler XYZ). The
 * composer's own ten `CameraMove` presets map onto library entries here, so
 * "pick a move" and "pick from the library" are the same mechanism.
 */

import * as THREE from 'three'
import type { CameraMove, CompositionKeyframe, Vec3 } from '../../../../types/film'
import { CAMERA_MOVE_PRESETS, type CameraMoveContext, type CameraMovePreset, type CameraMarkSpec } from './engine/camera-moves'
import { headingOf } from './engine/path'

/** Composer move → Blockout library id (the closest classic move). */
export const COMPOSER_MOVE_TO_PRESET: Record<CameraMove, string | null> = {
  static: null,
  push_in: 'slow-push-in',
  pull_out: 'pull-back-reveal',
  pan_left: 'static-pan-across',
  pan_right: 'static-pan-across',
  tilt_up: 'slow-tilt-reveal',
  tilt_down: 'crane-down-intro',
  dolly_left: 'side-track-left',
  dolly_right: 'side-track-right',
  orbit: 'orbit-90-left',
  follow: 'follow-behind',
}

export function presetById(id: string): CameraMovePreset | null {
  return CAMERA_MOVE_PRESETS.find(p => p.id === id) ?? null
}

export function libraryCategories(): { category: string; presets: CameraMovePreset[] }[] {
  const out = new Map<string, CameraMovePreset[]>()
  for (const preset of CAMERA_MOVE_PRESETS) {
    const list = out.get(preset.category) ?? []
    list.push(preset)
    out.set(preset.category, list)
  }
  return [...out.entries()].map(([category, presets]) => ({ category, presets }))
}

export interface MoveSubject {
  position: THREE.Vector3
  /** World yaw the subject faces (three.js rotation.y). */
  heading: number
  height: number
}

/** Pan (Blockout heading) from a three.js camera orientation. */
function panTiltOf(camera: THREE.PerspectiveCamera): { pan: number; tilt: number } {
  const dir = new THREE.Vector3()
  camera.getWorldDirection(dir)
  const flat = Math.hypot(dir.x, dir.z)
  return { pan: headingOf({ x: dir.x, y: 0, z: dir.z }), tilt: Math.atan2(dir.y, Math.max(flat, 1e-6)) }
}

/** Focal length (full-frame equivalent, mm) from a vertical FOV in degrees at 16:9. */
export function focalFromVfov(vfovDeg: number, aspect = 16 / 9): number {
  const hfov = 2 * Math.atan(Math.tan((vfovDeg * Math.PI) / 360) * aspect)
  return 36 / (2 * Math.tan(hfov / 2))
}

export function vfovFromFocal(focalMm: number, aspect = 16 / 9): number {
  const hfov = 2 * Math.atan(36 / (2 * focalMm))
  return (2 * Math.atan(Math.tan(hfov / 2) / aspect) * 180) / Math.PI
}

/** A Blockout mark → composer keyframe: position + Euler from pan/tilt/roll. */
export function markToKeyframe(mark: CameraMarkSpec, id: string, aspect = 16 / 9): CompositionKeyframe {
  const camera = new THREE.PerspectiveCamera(vfovFromFocal(mark.focalLength, aspect), aspect, 0.01, 100)
  camera.position.set(mark.position.x, mark.position.y, mark.position.z)
  // heading θ faces (−sinθ, 0, −cosθ); tilt positive looks up.
  const target = new THREE.Vector3(
    mark.position.x - Math.sin(mark.pan) * Math.cos(mark.tilt),
    mark.position.y + Math.sin(mark.tilt),
    mark.position.z - Math.cos(mark.pan) * Math.cos(mark.tilt),
  )
  camera.lookAt(target)
  camera.rotateZ(mark.roll)
  camera.updateMatrixWorld(true)
  const rotation = camera.rotation
  return {
    id,
    time: mark.time,
    transform: {
      position: [mark.position.x, mark.position.y, mark.position.z] as Vec3,
      rotation: [rotation.x, rotation.y, rotation.z] as Vec3,
      scale: [1, 1, 1] as Vec3,
    },
    fov: vfovFromFocal(mark.focalLength, aspect),
  }
}

/**
 * Run a library preset for a static subject and the live shot camera, and
 * return composer keyframes. Distances scale with `intensity` by moving the
 * subject sampler's aim height and the camera's start.
 */
export function keyframesFromPreset(
  preset: CameraMovePreset,
  camera: THREE.PerspectiveCamera,
  subject: MoveSubject,
  durationSeconds: number,
  aspect = 16 / 9,
): CompositionKeyframe[] {
  const { pan, tilt } = panTiltOf(camera)
  const ctx: CameraMoveContext = {
    subjectAt: () => ({ x: subject.position.x, y: subject.position.y, z: subject.position.z, heading: subject.heading }),
    subjectHeight: subject.height,
    camera: { x: camera.position.x, y: camera.position.y, z: camera.position.z, pan, tilt, focalLength: focalFromVfov(camera.fov, aspect) },
    duration: Math.max(0.5, durationSeconds),
  }
  const marks = preset.generate(ctx)
  return marks.map((mark, index) => markToKeyframe(mark, `kf-${preset.id}-${index}`, aspect))
}
