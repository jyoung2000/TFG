/**
 * Shot solver — turns semantic shot parameters (shot size, camera angle,
 * elevation, composition) into a camera position + look-at target, so nobody
 * hand-places XYZ coordinates.
 *
 * Adapted from Open Media's shot-composer `shotSolver.ts`
 * (github.com/Anujatk1999/open-media @ 9bfc076, MIT — see
 * docs/INTEGRATED_UPSTREAMS.md). Extended here with xwide/xcu shot sizes,
 * bird/worm elevations, POV/dutch angles (dutch adds camera roll), and the
 * OTS foreground/subject relationship carried on ShotFraming.
 */

import * as THREE from 'three'
import type { CameraAngle, CameraElevation, CompositionId, ShotSize } from '../../../types/film'
import { compositionTarget } from '../../../types/film'

export interface CharacterAnchors {
  feet: number
  hip: number
  chest: number
  head: number
  centerX: number
  centerZ: number
  height: number
  /** World yaw (radians) the character faces; 0 faces +Z (toward the "front" camera). */
  facingYaw: number
}

/** Derive framing anchors from an object's world bounding box + facing. */
export function getCharacterAnchors(root: THREE.Object3D): CharacterAnchors {
  root.updateWorldMatrix(true, true)
  const box = new THREE.Box3().setFromObject(root)
  const feet = box.min.y
  const height = Math.max(box.max.y - feet, 0.01)
  const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(
    root.getWorldQuaternion(new THREE.Quaternion()),
  )
  return {
    feet,
    hip: feet + height * 0.5,
    chest: feet + height * 0.72,
    head: feet + height * 0.93,
    centerX: (box.min.x + box.max.x) / 2,
    centerZ: (box.min.z + box.max.z) / 2,
    height,
    facingYaw: Math.atan2(forward.x, forward.z),
  }
}

/** Vertical frame span as fractions of character height measured from the feet. */
export const SHOT_SIZE_SPAN: Record<ShotSize, { bottom: number; top: number }> = {
  xwide: { bottom: -1.1, top: 1.6 },
  wide: { bottom: -0.35, top: 1.25 },
  full: { bottom: -0.05, top: 1.1 },
  medium: { bottom: 0.45, top: 1.15 },
  mcu: { bottom: 0.65, top: 1.15 },
  closeup: { bottom: 0.78, top: 1.12 },
  xcu: { bottom: 0.86, top: 1.02 },
}

const FRAME_FILL = 0.92

export const ANGLE_AZIMUTH_DEG: Record<CameraAngle, number> = {
  front: 0,
  threeQuarterRight: 45,
  threeQuarterLeft: -45,
  profile: 90,
  back: 180,
  // OTS is measured relative to the character's facing (leaning 30° off dead-
  // behind toward a shoulder); POV sits at the head looking where they look.
  ots: 150,
  pov: 0,
  dutch: -20,
}

/** How close an OTS camera hugs the foreground shoulder, per shot size. */
const OTS_PROXIMITY_RATIO: Record<ShotSize, number> = {
  xwide: 0.65,
  wide: 0.55,
  full: 0.45,
  medium: 0.38,
  mcu: 0.3,
  closeup: 0.22,
  xcu: 0.18,
}

export const ELEVATION_RATIO: Record<CameraElevation, number> = {
  worm: 0.02,
  low: 0.15,
  eye: 0.93,
  high: 1.35,
  bird: 2.6,
}

/** Camera roll in radians (dutch angle only). */
export const ANGLE_ROLL_RAD: Record<CameraAngle, number> = {
  front: 0,
  threeQuarterLeft: 0,
  threeQuarterRight: 0,
  profile: 0,
  back: 0,
  ots: 0,
  pov: 0,
  dutch: THREE.MathUtils.degToRad(18),
}

export interface SolveShotInput {
  shotSize: ShotSize
  angle: CameraAngle
  elevation: CameraElevation
  composition: CompositionId
  anchors: CharacterAnchors
  /** The character an OTS/POV shot looks toward. Ignored by other angles. */
  targetAnchors?: CharacterAnchors
  /** Which shoulder the OTS camera looks over (mirrors the OTS azimuth). */
  otsShoulder?: 'left' | 'right'
  fovDeg: number
  aspect: number
}

export interface SolvedShot {
  position: THREE.Vector3
  target: THREE.Vector3
  rollRad: number
}

export function solveShot(input: SolveShotInput): SolvedShot {
  const { anchors, targetAnchors, shotSize, angle, elevation, composition, fovDeg, aspect } = input
  const otsShoulder = input.otsShoulder ?? 'left'

  const span = SHOT_SIZE_SPAN[shotSize]
  const frameBottom = anchors.feet + span.bottom * anchors.height
  const frameTop = anchors.feet + span.top * anchors.height
  const frameCenterY = (frameBottom + frameTop) / 2
  const frameHeight = frameTop - frameBottom

  const isOTS = angle === 'ots'
  const isPOV = angle === 'pov'
  const vFovRad = THREE.MathUtils.degToRad(fovDeg)
  // OTS ignores frame-fill distance: it is defined by hugging the foreground
  // character's shoulder, not by framing them.
  const distance = isOTS
    ? OTS_PROXIMITY_RATIO[shotSize] * anchors.height
    : frameHeight / 2 / (FRAME_FILL * Math.tan(vFovRad / 2))

  // OTS/POV azimuths follow the character's current facing so the camera stays
  // behind the shoulder / at the eyes as they turn; other angles are world-fixed.
  const followsFacing = isOTS || isPOV
  // The right-shoulder OTS is the mirror image of the left-shoulder one.
  const azimuthDeg = isOTS && otsShoulder === 'right' ? -ANGLE_AZIMUTH_DEG.ots : ANGLE_AZIMUTH_DEG[angle]
  const azimuthRad = THREE.MathUtils.degToRad(azimuthDeg) + (followsFacing ? anchors.facingYaw : 0)

  let position: THREE.Vector3
  if (isPOV) {
    // Camera sits at the character's eyes, nudged forward so their own head
    // isn't in frame.
    const eyeY = anchors.feet + anchors.height * 0.93
    position = new THREE.Vector3(
      anchors.centerX + Math.sin(anchors.facingYaw) * anchors.height * 0.12,
      eyeY,
      anchors.centerZ + Math.cos(anchors.facingYaw) * anchors.height * 0.12,
    )
  } else {
    const cameraY = anchors.feet + ELEVATION_RATIO[elevation] * anchors.height
    position = new THREE.Vector3(
      anchors.centerX + Math.sin(azimuthRad) * distance,
      cameraY,
      anchors.centerZ + Math.cos(azimuthRad) * distance,
    )
  }

  // OTS/POV aim past/from the primary toward the secondary character, or along
  // the primary's facing when alone; every other angle frames the primary.
  const lookPastPrimary = isOTS || isPOV
  const subjectPoint = lookPastPrimary
    ? targetAnchors
      ? new THREE.Vector3(targetAnchors.centerX, targetAnchors.chest, targetAnchors.centerZ)
      : new THREE.Vector3(
          anchors.centerX + Math.sin(anchors.facingYaw) * anchors.height * 2,
          isPOV ? anchors.head : frameCenterY,
          anchors.centerZ + Math.cos(anchors.facingYaw) * anchors.height * 2,
        )
    : new THREE.Vector3(anchors.centerX, frameCenterY, anchors.centerZ)

  const forward = subjectPoint.clone().sub(position).normalize()
  const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize()
  const up = new THREE.Vector3().crossVectors(right, forward).normalize()

  const hFovRad = 2 * Math.atan(Math.tan(vFovRad / 2) * aspect)
  // Aiming at a point shifted toward right/up pushes the subject toward the
  // opposite screen edge, so both offsets invert the desired screen position.
  const { screenX, screenY } = compositionTarget(composition)
  const xOffset = 0.5 - screenX
  const yOffset = 0.5 - screenY
  const yawOffsetRad = Math.atan(xOffset * 2 * Math.tan(hFovRad / 2))
  const pitchOffsetRad = Math.atan(yOffset * 2 * Math.tan(vFovRad / 2))

  const aimDistance = subjectPoint.distanceTo(position)
  const target = subjectPoint
    .clone()
    .addScaledVector(right, aimDistance * Math.tan(yawOffsetRad))
    .addScaledVector(up, aimDistance * Math.tan(pitchOffsetRad))

  return { position, target, rollRad: ANGLE_ROLL_RAD[angle] }
}

/** Point a camera at a solved shot, applying dutch roll around the view axis. */
export function applySolvedShot(camera: THREE.PerspectiveCamera, shot: SolvedShot): void {
  camera.position.copy(shot.position)
  camera.up.set(0, 1, 0)
  camera.lookAt(shot.target)
  if (shot.rollRad !== 0) {
    const viewAxis = shot.target.clone().sub(shot.position).normalize()
    camera.rotateOnWorldAxis(viewAxis, shot.rollRad)
  }
  camera.updateMatrixWorld(true)
}
