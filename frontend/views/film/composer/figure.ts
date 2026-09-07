/**
 * Articulated mannequin built from three.js primitives.
 *
 * Replaces Open Media's mannequin-js dependency with a self-contained figure:
 * a named-joint hierarchy (rotations in Euler degrees) that the pose panel,
 * pose library and AI Director all share. Proportions are rough artist-
 * mannequin ratios; joints pivot at anatomically sensible points.
 */

import * as THREE from 'three'
import type { FigureVariant, Vec3 } from '../../../types/film'

export const FIGURE_HEIGHTS: Record<FigureVariant, number> = {
  male: 1.8,
  female: 1.65,
  child: 1.2,
}

/** Every poseable joint, in display order for the pose panel. */
export const JOINT_NAMES = [
  'torso',
  'neck',
  'head',
  'l_arm',
  'l_elbow',
  'l_wrist',
  'r_arm',
  'r_elbow',
  'r_wrist',
  'l_leg',
  'l_knee',
  'l_ankle',
  'r_leg',
  'r_knee',
  'r_ankle',
] as const

export type JointName = (typeof JOINT_NAMES)[number]

export const JOINT_LABELS: Record<JointName, string> = {
  torso: 'Torso',
  neck: 'Neck',
  head: 'Head',
  l_arm: 'L Shoulder',
  l_elbow: 'L Elbow',
  l_wrist: 'L Wrist',
  r_arm: 'R Shoulder',
  r_elbow: 'R Elbow',
  r_wrist: 'R Wrist',
  l_leg: 'L Hip',
  l_knee: 'L Knee',
  l_ankle: 'L Ankle',
  r_leg: 'R Hip',
  r_knee: 'R Knee',
  r_ankle: 'R Ankle',
}

export interface FigureRig {
  root: THREE.Group
  joints: Record<JointName, THREE.Group>
  height: number
  dispose: () => void
}

function capsule(
  radius: number,
  length: number,
  material: THREE.Material,
): THREE.Mesh {
  const geometry = new THREE.CapsuleGeometry(radius, length, 4, 10)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = true
  return mesh
}

/**
 * A limb segment whose pivot sits at the top: the joint group is placed at
 * the pivot and the capsule hangs below it, so rotating the group bends the
 * limb at the joint.
 */
function limbSegment(
  radius: number,
  length: number,
  material: THREE.Material,
): { joint: THREE.Group; mesh: THREE.Mesh } {
  const joint = new THREE.Group()
  const mesh = capsule(radius, Math.max(length - radius * 2, 0.02), material)
  mesh.position.y = -length / 2
  joint.add(mesh)
  return { joint, mesh }
}

export function buildFigure(variant: FigureVariant, colorHex: string): FigureRig {
  const height = FIGURE_HEIGHTS[variant]
  const scale = height / 1.8 // proportions authored for the 1.8 m male
  const color = new THREE.Color(colorHex)
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.05 })
  const accentMaterial = new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(0.8),
    roughness: 0.8,
    metalness: 0.05,
  })

  const geometries: THREE.BufferGeometry[] = []
  const track = <T extends THREE.Mesh>(mesh: T): T => {
    geometries.push(mesh.geometry)
    return mesh
  }

  const root = new THREE.Group()

  // Proportions (fractions of full height)
  const hipY = 0.52 * height
  const torsoLength = 0.28 * height
  const neckLength = 0.045 * height
  const headRadius = 0.072 * height
  const upperArm = 0.17 * height
  const forearm = 0.15 * height
  const hand = 0.07 * height
  const thigh = 0.26 * height
  const shin = 0.24 * height
  const foot = 0.1 * height
  const limbR = 0.032 * height
  const shoulderHalf = (variant === 'female' ? 0.1 : 0.115) * height
  const hipHalf = (variant === 'female' ? 0.075 : 0.066) * height

  // Pelvis block at the hip line.
  const pelvis = new THREE.Group()
  pelvis.position.y = hipY
  const pelvisMesh = track(
    new THREE.Mesh(
      new THREE.BoxGeometry(hipHalf * 2.3, 0.09 * height, 0.075 * height),
      accentMaterial,
    ),
  )
  pelvisMesh.castShadow = true
  pelvis.add(pelvisMesh)
  root.add(pelvis)

  // Torso pivots at the hip line.
  const torso = new THREE.Group()
  torso.name = 'torso'
  pelvis.add(torso)
  const chest = track(capsule(shoulderHalf * 0.92, torsoLength * 0.55, material))
  geometries.push(chest.geometry)
  chest.scale.z = 0.62
  chest.position.y = torsoLength * 0.62
  torso.add(chest)

  // Neck + head.
  const neck = new THREE.Group()
  neck.name = 'neck'
  neck.position.y = torsoLength
  torso.add(neck)
  const neckMesh = track(capsule(limbR * 0.85, neckLength, accentMaterial))
  neckMesh.position.y = neckLength / 2
  neck.add(neckMesh)

  const head = new THREE.Group()
  head.name = 'head'
  head.position.y = neckLength * 1.6
  neck.add(head)
  const skull = track(new THREE.Mesh(new THREE.SphereGeometry(headRadius, 18, 14), material))
  skull.castShadow = true
  skull.scale.set(0.82, 1, 0.9)
  skull.position.y = headRadius * 0.9
  head.add(skull)
  // Nose marker so facing reads clearly in the viewport.
  const nose = track(
    new THREE.Mesh(new THREE.ConeGeometry(headRadius * 0.22, headRadius * 0.55, 8), accentMaterial),
  )
  nose.rotation.x = Math.PI / 2
  nose.position.set(0, headRadius * 0.85, headRadius * 0.85)
  head.add(nose)

  const joints: Partial<Record<JointName, THREE.Group>> = {
    torso,
    neck,
    head,
  }

  // Arms: shoulder pivot at chest top corners.
  for (const side of ['l', 'r'] as const) {
    const sign = side === 'l' ? 1 : -1
    const shoulder = new THREE.Group()
    shoulder.name = `${side}_arm`
    shoulder.position.set(sign * shoulderHalf, torsoLength * 0.92, 0)
    torso.add(shoulder)
    const upper = limbSegment(limbR, upperArm, material)
    shoulder.add(upper.joint)
    track(upper.mesh)

    const elbow = new THREE.Group()
    elbow.name = `${side}_elbow`
    elbow.position.y = -upperArm
    upper.joint.add(elbow)
    const lower = limbSegment(limbR * 0.85, forearm, accentMaterial)
    elbow.add(lower.joint)
    track(lower.mesh)

    const wrist = new THREE.Group()
    wrist.name = `${side}_wrist`
    wrist.position.y = -forearm
    elbow.add(wrist)
    const palm = track(new THREE.Mesh(new THREE.BoxGeometry(limbR * 1.5, hand, limbR * 2.2), material))
    palm.castShadow = true
    palm.position.y = -hand / 2
    wrist.add(palm)

    joints[`${side}_arm`] = shoulder
    joints[`${side}_elbow`] = elbow
    joints[`${side}_wrist`] = wrist
  }

  // Legs: hip pivot on the pelvis.
  for (const side of ['l', 'r'] as const) {
    const sign = side === 'l' ? 1 : -1
    const hip = new THREE.Group()
    hip.name = `${side}_leg`
    hip.position.set(sign * hipHalf, 0, 0)
    pelvis.add(hip)
    const thighSegment = limbSegment(limbR * 1.15, thigh, material)
    hip.add(thighSegment.joint)
    track(thighSegment.mesh)

    const knee = new THREE.Group()
    knee.name = `${side}_knee`
    knee.position.y = -thigh
    thighSegment.joint.add(knee)
    const shinSegment = limbSegment(limbR * 0.95, shin, accentMaterial)
    knee.add(shinSegment.joint)
    track(shinSegment.mesh)

    const ankle = new THREE.Group()
    ankle.name = `${side}_ankle`
    ankle.position.y = -shin
    shinSegment.joint.add(ankle)
    const footMesh = track(
      new THREE.Mesh(new THREE.BoxGeometry(limbR * 2.2, limbR * 1.4, foot), material),
    )
    footMesh.castShadow = true
    footMesh.position.set(0, -limbR * 0.7, foot * 0.28)
    ankle.add(footMesh)

    joints[`${side}_leg`] = hip
    joints[`${side}_knee`] = knee
    joints[`${side}_ankle`] = ankle
  }

  root.scale.setScalar(1) // proportions already sized by `height`
  void scale

  return {
    root,
    joints: joints as Record<JointName, THREE.Group>,
    height,
    dispose: () => {
      for (const geometry of geometries) geometry.dispose()
      material.dispose()
      accentMaterial.dispose()
    },
  }
}

const toRad = (deg: number) => (deg * Math.PI) / 180
const toDeg = (rad: number) => (rad * 180) / Math.PI

/** Apply a named-joint pose (Euler degrees). Unlisted joints reset to zero. */
export function applyPose(rig: FigureRig, pose: Record<string, Vec3>): void {
  for (const name of JOINT_NAMES) {
    const joint = rig.joints[name]
    const euler = pose[name]
    if (euler) {
      joint.rotation.set(toRad(euler[0]), toRad(euler[1]), toRad(euler[2]), 'XYZ')
    } else {
      joint.rotation.set(0, 0, 0)
    }
  }
}

/** Read the rig's current joint rotations as a pose (Euler degrees). */
export function readPose(rig: FigureRig): Record<string, Vec3> {
  const pose: Record<string, Vec3> = {}
  for (const name of JOINT_NAMES) {
    const rotation = rig.joints[name].rotation
    if (rotation.x !== 0 || rotation.y !== 0 || rotation.z !== 0) {
      pose[name] = [
        Math.round(toDeg(rotation.x) * 10) / 10,
        Math.round(toDeg(rotation.y) * 10) / 10,
        Math.round(toDeg(rotation.z) * 10) / 10,
      ]
    }
  }
  return pose
}

/**
 * Limb-pair mirror: swaps each l_* joint with its r_* counterpart and negates
 * the yaw/roll axes so the pose reads as its left-right reflection. (Adapted
 * from Open Media's mirrorPosture limb-swap idea.)
 */
export function mirrorPose(pose: Record<string, Vec3>): Record<string, Vec3> {
  const mirrored: Record<string, Vec3> = {}
  const flip = (euler: Vec3): Vec3 => [euler[0], -euler[1], -euler[2]]
  for (const [name, euler] of Object.entries(pose)) {
    if (name.startsWith('l_')) mirrored[`r_${name.slice(2)}`] = flip(euler)
    else if (name.startsWith('r_')) mirrored[`l_${name.slice(2)}`] = flip(euler)
    else mirrored[name] = flip(euler)
  }
  return mirrored
}
