/**
 * Camera-motion presets: build a start/end camera keyframe pair from the
 * current solved camera, so a motion shot is "compose → pick a move →
 * keyframes exist". Adapts Open Media's motion-preset keyframe-builder
 * pattern (MIT) to camera moves instead of character gaits.
 */

import * as THREE from 'three'
import type { CameraMove, CompositionKeyframe, Vec3 } from '../../../types/film'

export interface CameraPose {
  position: THREE.Vector3
  target: THREE.Vector3
  fov: number
}

function toKeyframe(id: string, time: number, position: THREE.Vector3, target: THREE.Vector3, fov: number): CompositionKeyframe {
  const camera = new THREE.PerspectiveCamera(fov, 16 / 9, 0.01, 100)
  camera.position.copy(position)
  camera.lookAt(target)
  camera.updateMatrixWorld(true)
  const rotation = camera.rotation
  return {
    id,
    time,
    transform: {
      position: [position.x, position.y, position.z] as Vec3,
      rotation: [rotation.x, rotation.y, rotation.z] as Vec3,
      scale: [1, 1, 1] as Vec3,
    },
    fov,
  }
}

/**
 * Build the end pose of a camera move relative to its start pose. Distances
 * scale with the camera-subject distance so moves read consistently across
 * shot sizes.
 */
export function buildCameraMove(
  move: CameraMove,
  start: CameraPose,
  durationSeconds: number,
  /** 1 = the preset's default travel; 0.5 = half as far, 2 = twice as far. */
  intensity = 1,
): CompositionKeyframe[] {
  const makeId = () => `kf-${Math.random().toString(36).slice(2, 10)}`
  const startKf = toKeyframe(makeId(), 0, start.position, start.target, start.fov)
  if (move === 'static') return [startKf]

  const toSubject = start.target.clone().sub(start.position)
  const distance = Math.max(toSubject.length(), 0.5) * Math.min(Math.max(intensity, 0.1), 3)
  const forward = toSubject.clone().normalize()
  const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize()

  const endPosition = start.position.clone()
  const endTarget = start.target.clone()

  switch (move) {
    case 'push_in':
      endPosition.addScaledVector(forward, distance * 0.35)
      break
    case 'pull_out':
      endPosition.addScaledVector(forward, -distance * 0.45)
      break
    case 'pan_left':
      // Rotation only: target swings left around the camera.
      endTarget.addScaledVector(right, -distance * 0.6)
      break
    case 'pan_right':
      endTarget.addScaledVector(right, distance * 0.6)
      break
    case 'tilt_up':
      endTarget.y += distance * 0.45
      break
    case 'tilt_down':
      endTarget.y -= distance * 0.45
      break
    case 'dolly_left':
      endPosition.addScaledVector(right, -distance * 0.4)
      endTarget.addScaledVector(right, -distance * 0.4)
      break
    case 'dolly_right':
      endPosition.addScaledVector(right, distance * 0.4)
      endTarget.addScaledVector(right, distance * 0.4)
      break
    case 'orbit': {
      const offset = start.position.clone().sub(start.target)
      offset.applyAxisAngle(
        new THREE.Vector3(0, 1, 0),
        THREE.MathUtils.degToRad(50 * Math.min(Math.max(intensity, 0.1), 3)),
      )
      endPosition.copy(start.target).add(offset)
      break
    }
    case 'follow':
      // Subject-relative hold: end mirrors start; the motion reads through the
      // subject's own animation. Kept as two identical keys so duration shows.
      break
  }

  return [startKf, toKeyframe(makeId(), Math.max(durationSeconds, 0.5), endPosition, endTarget, start.fov)]
}

/** Linear position + slerp-equivalent lookAt sampling between two keyframes. */
export function sampleCameraTrack(
  keyframes: CompositionKeyframe[],
  time: number,
): { position: Vec3; rotation: Vec3; fov: number | null } | null {
  if (keyframes.length === 0) return null
  const sorted = [...keyframes].sort((a, b) => a.time - b.time)
  const first = sorted[0]
  const last = sorted[sorted.length - 1]
  if (time <= first.time) return { ...first.transform, fov: first.fov ?? null }
  if (time >= last.time) return { ...last.transform, fov: last.fov ?? null }
  let before = first
  let after = last
  for (let i = 0; i < sorted.length - 1; i++) {
    if (sorted[i].time <= time && time <= sorted[i + 1].time) {
      before = sorted[i]
      after = sorted[i + 1]
      break
    }
  }
  const span = after.time - before.time
  const t = span > 0 ? (time - before.time) / span : 0
  const lerp = (a: number, b: number) => a + (b - a) * t
  const beforeQuat = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(...before.transform.rotation, 'XYZ'),
  )
  const afterQuat = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(...after.transform.rotation, 'XYZ'),
  )
  const rotation = new THREE.Euler().setFromQuaternion(beforeQuat.slerp(afterQuat, t), 'XYZ')
  return {
    position: [
      lerp(before.transform.position[0], after.transform.position[0]),
      lerp(before.transform.position[1], after.transform.position[1]),
      lerp(before.transform.position[2], after.transform.position[2]),
    ],
    rotation: [rotation.x, rotation.y, rotation.z],
    fov:
      before.fov != null && after.fov != null
        ? lerp(before.fov, after.fov)
        : (before.fov ?? after.fov ?? null),
  }
}
