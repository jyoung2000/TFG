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
import { BODY_SHAPES, type Ring, type Taper } from './anatomy'

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
  variant: FigureVariant
  dispose: () => void
}

/**
 * A body section lofted through elliptical rings (asked 2026-10-01: real
 * anatomy) - a ribcage narrowing to a waist, a muscled limb tapering to the
 * wrist. Rings may come in any order; they are sorted bottom to top.
 */
export function loftGeometry(rings: Ring[], segments = 20): THREE.BufferGeometry {
  const sorted = [...rings].sort((a, b) => a.y - b.y)
  const positions: number[] = []
  const index: number[] = []
  for (const ring of sorted) {
    for (let j = 0; j < segments; j++) {
      const angle = (j / segments) * Math.PI * 2
      positions.push(Math.cos(angle) * ring.rx, ring.y, (ring.z ?? 0) + Math.sin(angle) * ring.rz)
    }
  }
  for (let i = 0; i < sorted.length - 1; i++) {
    for (let j = 0; j < segments; j++) {
      const a = i * segments + j
      const b = i * segments + ((j + 1) % segments)
      const c = a + segments
      const d = b + segments
      index.push(a, c, b, b, c, d)
    }
  }
  const bottom = positions.length / 3
  positions.push(0, sorted[0].y, sorted[0].z ?? 0)
  const top = bottom + 1
  const last = sorted[sorted.length - 1]
  positions.push(0, last.y, last.z ?? 0)
  const lastRing = (sorted.length - 1) * segments
  for (let j = 0; j < segments; j++) {
    index.push(bottom, j, (j + 1) % segments)
    index.push(top, lastRing + ((j + 1) % segments), lastRing + j)
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setIndex(index)
  geometry.computeVertexNormals()
  return geometry
}

/** A limb hanging from its joint along -Y: radii from `taper` (x height), rounded at both ends. */
function limbGeometry(taper: Taper, length: number, height: number, depth = 0.94): THREE.BufferGeometry {
  const r0 = taper[0][1] * height
  const r1 = taper[taper.length - 1][1] * height
  const rings: Ring[] = [
    { y: r0 * 0.55, rx: r0 * 0.55, rz: r0 * 0.55 * depth },
    ...taper.map(([t, r]) => ({ y: -t * length, rx: r * height, rz: r * height * depth })),
    { y: -length - r1 * 0.55, rx: r1 * 0.55, rz: r1 * 0.55 * depth },
  ]
  return loftGeometry(rings, 16)
}

export function buildFigure(variant: FigureVariant, colorHex: string): FigureRig {
  const height = FIGURE_HEIGHTS[variant]
  const shape = BODY_SHAPES[variant]
  const H = height
  const color = new THREE.Color(colorHex)
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.05 })
  const accentMaterial = new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(0.85),
    roughness: 0.75,
    metalness: 0.05,
  })

  const geometries: THREE.BufferGeometry[] = []
  const mesh = (geometry: THREE.BufferGeometry, mat: THREE.Material = material): THREE.Mesh => {
    geometries.push(geometry)
    const m = new THREE.Mesh(geometry, mat)
    m.castShadow = true
    return m
  }

  const root = new THREE.Group()

  // Bone lengths (fractions of full height).
  const hipY = 0.52 * H
  const torsoLength = 0.28 * H
  const neckLength = 0.045 * H
  const headRadius = 0.072 * H
  const upperArm = 0.17 * H
  const forearm = 0.15 * H
  const thigh = 0.26 * H
  const shin = 0.24 * H
  const scaleRings = (rings: Ring[], yUnit: number) => rings.map(r => ({ y: r.y * yUnit, rx: r.rx * H, rz: r.rz * H, z: (r.z ?? 0) * H }))

  // Pelvis: the hips and seat around the hip line.
  const pelvis = new THREE.Group()
  pelvis.position.y = hipY
  pelvis.add(mesh(loftGeometry(scaleRings(shape.pelvis, H)), accentMaterial))
  root.add(pelvis)

  // Torso pivots at the hip line: belly, waist, ribcage, chest, shoulders.
  const torso = new THREE.Group()
  torso.name = 'torso'
  pelvis.add(torso)
  torso.add(mesh(loftGeometry(scaleRings(shape.torso, torsoLength), 24)))
  for (const b of shape.bust) {
    const breast = mesh(new THREE.SphereGeometry(b.r * H, 16, 12))
    breast.scale.set(1, 0.95, 0.8)
    breast.position.set(b.x * H, b.y * torsoLength, b.z * H)
    torso.add(breast)
  }

  // Neck + head.
  const neck = new THREE.Group()
  neck.name = 'neck'
  neck.position.y = torsoLength
  torso.add(neck)
  neck.add(mesh(loftGeometry(scaleRings(shape.neck, neckLength * 1.7), 14), accentMaterial))

  const head = new THREE.Group()
  head.name = 'head'
  head.position.y = neckLength * 1.6
  neck.add(head)
  const skull = mesh(new THREE.SphereGeometry(headRadius, 20, 16))
  skull.scale.set(0.82, 1, 0.9)
  skull.position.y = headRadius * 0.9
  head.add(skull)
  const jaw = mesh(new THREE.SphereGeometry(headRadius * 0.62, 16, 12))
  jaw.scale.set(0.95, 0.8, 1)
  jaw.position.set(0, headRadius * 0.42, headRadius * 0.22)
  head.add(jaw)
  // Nose so facing reads clearly in the viewport.
  const nose = mesh(new THREE.ConeGeometry(headRadius * 0.16, headRadius * 0.4, 8), accentMaterial)
  nose.rotation.x = Math.PI / 2
  nose.position.set(0, headRadius * 0.82, headRadius * 0.9)
  head.add(nose)
  for (const sign of [1, -1]) {
    const ear = mesh(new THREE.SphereGeometry(headRadius * 0.2, 10, 8), accentMaterial)
    ear.scale.set(0.35, 1, 0.65)
    ear.position.set(sign * headRadius * 0.8, headRadius * 0.85, -headRadius * 0.05)
    head.add(ear)
  }

  const joints: Partial<Record<JointName, THREE.Group>> = { torso, neck, head }

  /** The unnamed segment a limb hangs in, holding that limb's one mesh. */
  const segment = (geometry: THREE.BufferGeometry, mat: THREE.Material) => {
    const wrapper = new THREE.Group()
    wrapper.add(mesh(geometry, mat))
    return wrapper
  }

  // Arms: shoulder pivot at the top corners of the ribcage.
  for (const side of ['l', 'r'] as const) {
    const sign = side === 'l' ? 1 : -1
    const shoulder = new THREE.Group()
    shoulder.name = `${side}_arm`
    shoulder.position.set(sign * shape.shoulderHalf * H, torsoLength * 0.92, 0)
    torso.add(shoulder)
    const upper = segment(limbGeometry(shape.upperArm, upperArm, H), material)
    shoulder.add(upper)

    const elbow = new THREE.Group()
    elbow.name = `${side}_elbow`
    elbow.position.y = -upperArm
    upper.add(elbow)
    const lower = segment(limbGeometry(shape.forearm, forearm, H, 0.85), accentMaterial)
    elbow.add(lower)

    const wrist = new THREE.Group()
    wrist.name = `${side}_wrist`
    wrist.position.y = -forearm
    lower.add(wrist)
    // Hand: the palm faces the thigh, the thumb forward, four fingers.
    const { palm, fingers, width, thickness } = shape.hand
    const palmMesh = mesh(new THREE.BoxGeometry(thickness * H, palm * H, width * H))
    palmMesh.position.y = (-palm * H) / 2
    wrist.add(palmMesh)
    const fingerR = thickness * H * 0.32
    const shares = [0.92, 1, 0.95, 0.78]
    shares.forEach((share, i) => {
      const length = fingers * H * share
      const finger = mesh(new THREE.CapsuleGeometry(fingerR, Math.max(0.005, length - fingerR * 2), 3, 6))
      finger.position.set(0, -palm * H - length / 2, (0.36 - i * 0.24) * width * H)
      wrist.add(finger)
    })
    const thumbLength = fingers * H * 0.75
    const thumb = mesh(new THREE.CapsuleGeometry(fingerR * 1.1, thumbLength - fingerR * 2, 3, 6))
    thumb.rotation.x = 0.55
    thumb.position.set(0, -palm * H * 0.45, width * H * 0.55)
    wrist.add(thumb)

    joints[`${side}_arm`] = shoulder
    joints[`${side}_elbow`] = elbow
    joints[`${side}_wrist`] = wrist
  }

  // Legs: hip pivot on the pelvis.
  for (const side of ['l', 'r'] as const) {
    const sign = side === 'l' ? 1 : -1
    const hip = new THREE.Group()
    hip.name = `${side}_leg`
    hip.position.set(sign * shape.hipHalf * H, 0, 0)
    pelvis.add(hip)
    const thighSegment = segment(limbGeometry(shape.thigh, thigh, H), material)
    hip.add(thighSegment)

    const knee = new THREE.Group()
    knee.name = `${side}_knee`
    knee.position.y = -thigh
    thighSegment.add(knee)
    const shinSegment = segment(limbGeometry(shape.shin, shin, H, 0.9), accentMaterial)
    knee.add(shinSegment)

    const ankle = new THREE.Group()
    ankle.name = `${side}_ankle`
    ankle.position.y = -shin
    shinSegment.add(ankle)
    // Foot: heel behind the ankle, toes tapering down to the floor.
    const { heel, toe, width, height: footHeight } = shape.foot
    const footLength = (heel + toe) * H
    const footGeometry = new THREE.BoxGeometry(width * H, footHeight * H * 0.75, footLength, 1, 1, 4)
    const position = footGeometry.attributes.position
    for (let i = 0; i < position.count; i++) {
      const z = position.getZ(i) / (footLength / 2)
      if (position.getY(i) > 0 && z > 0) position.setY(i, position.getY(i) * (1 - 0.7 * z))
      if (z > 0.6) position.setX(i, position.getX(i) * 1.1)
    }
    footGeometry.computeVertexNormals()
    const footMesh = mesh(footGeometry)
    footMesh.position.set(0, -0.02 * H + (footHeight * H * 0.75) / 2, ((toe - heel) * H) / 2)
    ankle.add(footMesh)

    joints[`${side}_leg`] = hip
    joints[`${side}_knee`] = knee
    joints[`${side}_ankle`] = ankle
  }

  return {
    root,
    joints: joints as Record<JointName, THREE.Group>,
    height,
    variant,
    dispose: () => {
      for (const geometry of geometries) geometry.dispose()
      material.dispose()
      accentMaterial.dispose()
    },
  }
}

/**
 * The posable joint a clicked part of a figure belongs to: the nearest named
 * joint above it in the rig (a forearm is the elbow, an upper arm the
 * shoulder). Null for the pelvis or anything outside a rig.
 */
export function jointForObject(object: THREE.Object3D | null): JointName | null {
  let current = object
  while (current) {
    if ((JOINT_NAMES as readonly string[]).includes(current.name)) return current.name as JointName
    if (current.userData.entityId) return null
    current = current.parent
  }
  return null
}

/**
 * The meshes of one joint's own section: what hangs from it up to the next
 * joint (the forearm for the elbow, not the hand below the wrist).
 */
export function sectionMeshes(rig: FigureRig, joint: JointName): THREE.Mesh[] {
  const meshes: THREE.Mesh[] = []
  for (const child of rig.joints[joint].children) {
    if (child instanceof THREE.Mesh) meshes.push(child)
    else if (child.name === '') {
      // The unnamed segment a limb hangs in; named children are other joints.
      for (const inner of child.children) if (inner instanceof THREE.Mesh) meshes.push(inner)
    }
  }
  return meshes
}

/**
 * Light up just these meshes (or restore them with `null`). A figure's limbs
 * share one material, so each tinted mesh gets its own copy and gets the
 * shared one back afterwards.
 */
export function tintMeshes(meshes: THREE.Mesh[], hex: string | null): void {
  for (const mesh of meshes) {
    const base = (mesh.userData.baseMaterial ??= mesh.material) as THREE.MeshStandardMaterial
    if (mesh.material !== base) (mesh.material as THREE.Material).dispose()
    if (hex === null) {
      mesh.material = base
      continue
    }
    const tinted = base.clone()
    tinted.emissive = new THREE.Color(hex)
    tinted.emissiveIntensity = 0.6
    mesh.material = tinted
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


/**
 * Distance-tied walk cycle (adapted from mangerik/Blocking-Room `src/spatial.js`
 * `gait()`, MIT — see docs/INTEGRATED_UPSTREAMS.md): the limb swing is a
 * function of metres travelled, so the same timeline time always shows the
 * same stride, and it fades in/out over the first and last 0.15 s of a leg.
 * Returns the swing angle in radians for hips (legs opposite) and shoulders.
 */
export function walkSwing(distance: number, speed: number, envelope = 1): number {
  const stride = 1.15
  return Math.sin((distance / stride) * Math.PI * 2) * 0.55 * Math.min(1, speed / 0.8) * Math.max(0, Math.min(1, envelope))
}

/** Layer the walk cycle over a base pose without touching the rig's stored pose. */
export function applyWalkCycle(rig: FigureRig, basePose: Record<string, Vec3>, distance: number, speed: number, envelope = 1): void {
  applyPose(rig, basePose)
  const swing = walkSwing(distance, speed, envelope)
  if (Math.abs(swing) < 1e-4) return
  rig.joints.l_leg.rotation.x += swing
  rig.joints.r_leg.rotation.x -= swing
  rig.joints.l_arm.rotation.x -= swing * 0.7
  rig.joints.r_arm.rotation.x += swing * 0.7
  rig.joints.l_knee.rotation.x += Math.max(0, -swing) * 0.8
  rig.joints.r_knee.rotation.x += Math.max(0, swing) * 0.8
}
