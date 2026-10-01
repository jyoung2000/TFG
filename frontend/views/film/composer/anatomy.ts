/**
 * The mannequin's body (asked 2026-10-01: "ensure the models have real
 * anatomy and the models can't clip into themselves, i shouldnt be able to
 * drag the arm through the chest").
 *
 *   - BODY_SHAPES: adult proportions per variant - a ribcage, a waist, hips,
 *     muscled tapering limbs. `figure.ts` builds the meshes from them and the
 *     collision volumes below are the same numbers, so what blocks a limb is
 *     the surface the user sees.
 *   - JOINT_LIMITS: elbows and knees are hinges that bend one way; the neck,
 *     head, spine, wrists and ankles turn only as far as a body does.
 *   - selfContacts / constrainPose: an edit that would push one part of the
 *     body into another stops where they touch (limbs may touch, as a hand on
 *     a hip does, but not pass through).
 *
 * All sizes are fractions of the figure's height. The figure faces +Z, its
 * left is +X, limbs hang along -Y from their joint.
 */

import * as THREE from 'three'
import type { FigureVariant } from '../../../types/film'
import type { FigureRig, JointName } from './figure'

/** One elliptical cross-section of a body volume: centre z offset, half-width, half-depth. */
export interface Ring {
  y: number
  rx: number
  rz: number
  z?: number
}

/** A limb's radius along its length: [t from the joint (0) to the next (1), radius]. */
export type Taper = [number, number][]

export interface BodyShape {
  /** Shoulder joints at ±shoulderHalf; hip joints at ±hipHalf. */
  shoulderHalf: number
  hipHalf: number
  /** Ribcage to neck, y as a fraction of the torso length (pivot at the hip line). */
  torso: Ring[]
  /** Breasts: spheres in the torso's frame (y as a fraction of the torso length). */
  bust: { x: number; y: number; z: number; r: number }[]
  /** The pelvis around the hip line, y in height fractions. */
  pelvis: Ring[]
  neck: Ring[]
  upperArm: Taper
  forearm: Taper
  thigh: Taper
  shin: Taper
  /** Hand: palm + fingers along -Y from the wrist. */
  hand: { palm: number; fingers: number; width: number; thickness: number }
  /** Foot: heel (behind the ankle) to toes (ahead of it). */
  foot: { heel: number; toe: number; width: number; height: number }
}

const scaleTaper = (taper: Taper, k: number): Taper => taper.map(([t, r]) => [t, r * k])

const MALE: BodyShape = {
  shoulderHalf: 0.13,
  hipHalf: 0.052,
  torso: [
    { y: 0.0, rx: 0.085, rz: 0.06 },
    { y: 0.18, rx: 0.076, rz: 0.055, z: 0.004 },
    { y: 0.42, rx: 0.082, rz: 0.058, z: 0.006 },
    { y: 0.66, rx: 0.092, rz: 0.064, z: 0.008 },
    { y: 0.84, rx: 0.094, rz: 0.06, z: 0.002 },
    { y: 0.95, rx: 0.074, rz: 0.048 },
    { y: 1.0, rx: 0.03, rz: 0.03 },
  ],
  bust: [],
  pelvis: [
    { y: -0.075, rx: 0.07, rz: 0.052, z: -0.004 },
    { y: -0.04, rx: 0.086, rz: 0.06, z: -0.006 },
    { y: 0.0, rx: 0.088, rz: 0.06, z: -0.004 },
    { y: 0.04, rx: 0.084, rz: 0.058 },
  ],
  neck: [
    { y: 0, rx: 0.031, rz: 0.033 },
    { y: 1, rx: 0.027, rz: 0.029 },
  ],
  upperArm: [[0, 0.05], [0.25, 0.044], [0.55, 0.04], [0.85, 0.034], [1, 0.031]],
  forearm: [[0, 0.032], [0.2, 0.034], [0.6, 0.027], [1, 0.02]],
  thigh: [[0, 0.06], [0.4, 0.052], [0.8, 0.04], [1, 0.036]],
  shin: [[0, 0.036], [0.25, 0.04], [0.6, 0.03], [1, 0.022]],
  hand: { palm: 0.058, fingers: 0.047, width: 0.05, thickness: 0.02 },
  foot: { heel: 0.035, toe: 0.115, width: 0.05, height: 0.04 },
}

const FEMALE: BodyShape = {
  shoulderHalf: 0.125,
  hipHalf: 0.05,
  torso: [
    { y: 0.0, rx: 0.088, rz: 0.06 },
    { y: 0.25, rx: 0.064, rz: 0.05, z: 0.003 },
    { y: 0.48, rx: 0.072, rz: 0.052, z: 0.006 },
    { y: 0.66, rx: 0.079, rz: 0.055, z: 0.008 },
    { y: 0.84, rx: 0.083, rz: 0.053, z: 0.002 },
    { y: 0.95, rx: 0.066, rz: 0.044 },
    { y: 1.0, rx: 0.028, rz: 0.028 },
  ],
  bust: [
    { x: 0.037, y: 0.64, z: 0.042, r: 0.032 },
    { x: -0.037, y: 0.64, z: 0.042, r: 0.032 },
  ],
  pelvis: [
    { y: -0.075, rx: 0.072, rz: 0.056, z: -0.006 },
    { y: -0.04, rx: 0.092, rz: 0.064, z: -0.01 },
    { y: 0.0, rx: 0.092, rz: 0.062, z: -0.008 },
    { y: 0.04, rx: 0.086, rz: 0.058 },
  ],
  neck: [
    { y: 0, rx: 0.027, rz: 0.029 },
    { y: 1, rx: 0.024, rz: 0.026 },
  ],
  upperArm: scaleTaper(MALE.upperArm, 0.85),
  forearm: scaleTaper(MALE.forearm, 0.88),
  thigh: [[0, 0.062], [0.4, 0.053], [0.8, 0.039], [1, 0.034]],
  shin: scaleTaper(MALE.shin, 0.92),
  hand: { palm: 0.055, fingers: 0.045, width: 0.045, thickness: 0.018 },
  foot: { heel: 0.033, toe: 0.11, width: 0.045, height: 0.037 },
}

export const BODY_SHAPES: Record<FigureVariant, BodyShape> = { male: MALE, female: FEMALE, child: MALE }

/** Radius of a taper at `t` (linear between its stations). */
export function taperAt(taper: Taper, t: number): number {
  if (t <= taper[0][0]) return taper[0][1]
  for (let i = 1; i < taper.length; i++) {
    const [t1, r1] = taper[i]
    const [t0, r0] = taper[i - 1]
    if (t <= t1) return r0 + ((r1 - r0) * (t - t0)) / Math.max(1e-9, t1 - t0)
  }
  return taper[taper.length - 1][1]
}

// ---- Joint limits -------------------------------------------------------

/** Euler XYZ degrees each joint can reach. Joints not listed (shoulders, hips) are ball joints, held only by the body. */
export const JOINT_LIMITS: Partial<Record<JointName, [number, number][]>> = {
  // A hinge: the forearm folds toward the front of the upper arm (-X), the
  // forearm twists (Y); it does not bend sideways.
  l_elbow: [[-150, 5], [-90, 90], [-10, 10]],
  r_elbow: [[-150, 5], [-90, 90], [-10, 10]],
  // The shin folds back (+X).
  l_knee: [[-5, 150], [-20, 20], [-8, 8]],
  r_knee: [[-5, 150], [-20, 20], [-8, 8]],
  l_wrist: [[-80, 80], [-30, 30], [-40, 40]],
  r_wrist: [[-80, 80], [-30, 30], [-40, 40]],
  // Toes up is -X, pointing them +X.
  l_ankle: [[-30, 45], [-25, 25], [-25, 25]],
  r_ankle: [[-30, 45], [-25, 25], [-25, 25]],
  // Forward is +X for the spine, neck and head.
  torso: [[-30, 90], [-50, 50], [-40, 40]],
  neck: [[-45, 60], [-70, 70], [-40, 40]],
  head: [[-40, 40], [-60, 60], [-30, 30]],
}

const DEG = Math.PI / 180

/** Clamp `joints` into their ranges; returns the joints that were at a limit. */
export function clampJoints(rig: FigureRig, joints: Iterable<JointName>): JointName[] {
  const limited: JointName[] = []
  for (const name of joints) {
    const limits = JOINT_LIMITS[name]
    if (!limits) continue
    const rotation = rig.joints[name].rotation
    const values = [rotation.x, rotation.y, rotation.z]
    let hit = false
    const clamped = values.map((value, axis) => {
      const [lo, hi] = limits[axis]
      const next = THREE.MathUtils.clamp(value, lo * DEG, hi * DEG)
      if (Math.abs(next - value) > 1e-6) hit = true
      return next
    })
    if (hit) {
      rotation.set(clamped[0], clamped[1], clamped[2], 'XYZ')
      limited.push(name)
    }
  }
  if (limited.length) rig.root.updateMatrixWorld(true)
  return limited
}

// ---- Self-collision ------------------------------------------------------

/** Limbs may touch (a hand on a hip): only overlap past this share of a limb's radius counts. */
const SOFT = 0.85
/** Overlap below this (× height) is noise, not a clip. */
const EPS = 0.002

interface Sphere { centre: THREE.Vector3; r: number; part: string; t: number }
interface Volume { name: (y: number) => string; frame: THREE.Object3D; rings: Ring[] }

export interface Contact { a: string; b: string; depth: number }

const SIDES = [['l', 'left'], ['r', 'right']] as const

function worldOf(object: THREE.Object3D, local = new THREE.Vector3()): THREE.Vector3 {
  return local.clone().applyMatrix4(object.matrixWorld)
}

/** Spheres along a limb from `a` to `b` (world), radii from `radius` (× world height). */
function chain(part: string, a: THREE.Vector3, b: THREE.Vector3, radius: (t: number) => number, count: number, height: number): Sphere[] {
  const spheres: Sphere[] = []
  for (let i = 0; i < count; i++) {
    const t = i / (count - 1)
    spheres.push({ centre: a.clone().lerp(b, t), r: radius(t) * height * SOFT, part, t })
  }
  return spheres
}

function limbSpheres(rig: FigureRig, shape: BodyShape, worldScale: number): Sphere[] {
  const H = rig.height
  const worldH = H * worldScale
  const j = rig.joints
  const spheres: Sphere[] = []
  for (const [s, side] of SIDES) {
    const at = (name: JointName) => worldOf(j[name])
    spheres.push(...chain(`${side} upper arm`, at(`${s}_arm`), at(`${s}_elbow`), t => taperAt(shape.upperArm, t), 6, worldH))
    spheres.push(...chain(`${side} forearm`, at(`${s}_elbow`), at(`${s}_wrist`), t => taperAt(shape.forearm, t), 6, worldH))
    const handEnd = worldOf(j[`${s}_wrist`], new THREE.Vector3(0, -(shape.hand.palm + shape.hand.fingers) * 0.85 * H, 0))
    spheres.push(...chain(`${side} hand`, at(`${s}_wrist`), handEnd, () => shape.hand.width * 0.42, 4, worldH))
    spheres.push(...chain(`${side} thigh`, at(`${s}_leg`), at(`${s}_knee`), t => taperAt(shape.thigh, t), 6, worldH))
    spheres.push(...chain(`${side} shin`, at(`${s}_knee`), at(`${s}_ankle`), t => taperAt(shape.shin, t), 6, worldH))
    const heel = worldOf(j[`${s}_ankle`], new THREE.Vector3(0, -0.008 * H, -shape.foot.heel * 0.6 * H))
    const toe = worldOf(j[`${s}_ankle`], new THREE.Vector3(0, -0.008 * H, shape.foot.toe * 0.85 * H))
    spheres.push(...chain(`${side} foot`, heel, toe, () => shape.foot.width * 0.45, 5, worldH))
  }
  return spheres
}

function bodyVolumes(rig: FigureRig, shape: BodyShape): Volume[] {
  const H = rig.height
  const torsoLength = 0.28 * H
  const pelvis = rig.joints.torso.parent ?? rig.root
  const headRings: Ring[] = []
  const headR = 0.072 * H
  for (let i = -4; i <= 4; i++) {
    const phi = (i / 5) * (Math.PI / 2)
    headRings.push({ y: headR * 0.9 + headR * Math.sin(phi), rx: 0.82 * headR * Math.cos(phi), rz: 0.9 * headR * Math.cos(phi) })
  }
  return [
    {
      name: y => (y > 0.5 * torsoLength ? 'chest' : 'belly'),
      frame: rig.joints.torso,
      rings: shape.torso.map(r => ({ y: r.y * torsoLength, rx: r.rx * H, rz: r.rz * H, z: (r.z ?? 0) * H })),
    },
    { name: () => 'hips', frame: pelvis, rings: shape.pelvis.map(r => ({ y: r.y * H, rx: r.rx * H, rz: r.rz * H, z: (r.z ?? 0) * H })) },
    { name: () => 'head', frame: rig.joints.head, rings: headRings },
  ]
}

/** How far a sphere (world centre and radius) is inside a volume, in world units; 0 outside. */
function volumeDepth(volume: Volume, sphere: Sphere, inverse: THREE.Matrix4, unit: number): { depth: number; y: number } {
  const p = sphere.centre.clone().applyMatrix4(inverse)
  const r = sphere.r / unit
  const rings = volume.rings
  if (p.y < rings[0].y || p.y > rings[rings.length - 1].y) return { depth: 0, y: p.y }
  let i = 1
  while (i < rings.length - 1 && rings[i].y < p.y) i++
  const a = rings[i - 1]
  const b = rings[i]
  const k = (p.y - a.y) / Math.max(1e-9, b.y - a.y)
  const rx = a.rx + (b.rx - a.rx) * k + r
  const rz = a.rz + (b.rz - a.rz) * k + r
  const zc = (a.z ?? 0) + ((b.z ?? 0) - (a.z ?? 0)) * k
  const q = (p.x / rx) ** 2 + ((p.z - zc) / rz) ** 2
  return { depth: q < 1 ? (1 - Math.sqrt(q)) * Math.min(rx, rz) * unit : 0, y: p.y }
}

/** Where a limb meets the trunk at its joint, the part next to the joint is exempt. */
function exempt(part: string, t: number, volume: string): boolean {
  if (part.endsWith('upper arm') && (volume === 'chest' || volume === 'belly')) return t < 0.35
  if (part.endsWith('thigh') && volume === 'hips') return true
  if (part.endsWith('thigh') && (volume === 'belly' || volume === 'chest')) return t < 0.4
  return false
}

const limbOf = (part: string) => part.split(' ')[0] + (/(arm|hand)$/.test(part) ? ' arm' : ' leg')

/**
 * Where the body passes through itself: the total depth of every overlap
 * (world metres) and the deepest pair, e.g. "left forearm" / "chest".
 */
export function selfContacts(rig: FigureRig): { depth: number; worst: Contact | null } {
  const shape = BODY_SHAPES[rig.variant]
  rig.root.updateMatrixWorld(true)
  const worldScale = rig.root.getWorldScale(new THREE.Vector3()).y
  const spheres = limbSpheres(rig, shape, worldScale)
  let depth = 0
  let worst: Contact | null = null
  const note = (a: string, b: string, d: number) => {
    if (d <= 0) return
    depth += d
    if (!worst || d > worst.depth) worst = { a, b, depth: d }
  }
  // Limbs against the trunk and head.
  for (const volume of bodyVolumes(rig, shape)) {
    const inverse = volume.frame.matrixWorld.clone().invert()
    for (const sphere of spheres) {
      const probe = volumeDepth(volume, sphere, inverse, worldScale)
      if (probe.depth <= 0) continue
      const name = volume.name(probe.y)
      if (!exempt(sphere.part, sphere.t, name)) note(sphere.part, name, probe.depth)
    }
  }
  // Limbs against the bust.
  const torsoLength = 0.28 * rig.height
  for (const b of shape.bust) {
    const centre = worldOf(rig.joints.torso, new THREE.Vector3(b.x * rig.height, b.y * torsoLength, b.z * rig.height))
    const r = b.r * rig.height * worldScale
    for (const sphere of spheres) {
      if (sphere.part.endsWith('upper arm') && sphere.t < 0.35) continue
      note(sphere.part, 'chest', r + sphere.r - sphere.centre.distanceTo(centre))
    }
  }
  // Limbs against each other (not within one limb, which its joints govern).
  for (let i = 0; i < spheres.length; i++) {
    const a = spheres[i]
    for (let k = i + 1; k < spheres.length; k++) {
      const b = spheres[k]
      if (limbOf(a.part) === limbOf(b.part)) continue
      if (a.part.endsWith('thigh') && b.part.endsWith('thigh') && (a.t < 0.3 || b.t < 0.3)) continue
      note(a.part, b.part, a.r + b.r - a.centre.distanceTo(b.centre))
    }
  }
  return { depth, worst }
}

// ---- Constraining an edit -------------------------------------------------

export type PoseSnapshot = Map<JointName, THREE.Quaternion>

export function snapshotPose(rig: FigureRig): PoseSnapshot {
  const snapshot: PoseSnapshot = new Map()
  for (const [name, joint] of Object.entries(rig.joints) as [JointName, THREE.Object3D][]) snapshot.set(name, joint.quaternion.clone())
  return snapshot
}

/** Put the rig at `from`, or `t` of the way from `from` to `to`. */
function restore(rig: FigureRig, from: PoseSnapshot, to: PoseSnapshot | null, t: number): void {
  for (const [name, q] of from) {
    const joint = rig.joints[name]
    joint.quaternion.copy(q)
    if (to) joint.quaternion.slerp(to.get(name) ?? q, t)
  }
  rig.root.updateMatrixWorld(true)
}

export interface Constrained {
  /** The parts that would have passed through each other, if the edit was stopped. */
  blocked: Contact | null
  /** Joints the edit pushed to the end of their range. */
  limited: JointName[]
}

/** Path checks per edit: a big jump (an IK solution flipping round the body) cannot tunnel through it. */
const PATH_SAMPLES = 8

/**
 * Keep an edit anatomical: joints the edit moved are held to their ranges,
 * and if the edit - anywhere along the way from the pose before it - pushes
 * one part of the body into another it goes only as far as they touch. An
 * edit away from a clip the pose already had is let through, so a loaded
 * pose that clips never traps the user.
 */
export function constrainPose(rig: FigureRig, before: PoseSnapshot): Constrained {
  const changed = [...before].filter(([name, q]) => rig.joints[name].quaternion.angleTo(q) > 1e-6).map(([name]) => name)
  if (!changed.length) return { blocked: null, limited: [] }
  const limited = clampJoints(rig, changed)
  const after = snapshotPose(rig)
  restore(rig, before, null, 0)
  // Overlap allowed: what the pose already had (never more), or noise.
  const already = selfContacts(rig).depth
  const allowed = Math.max(already, EPS * rig.height)
  if (already > EPS * rig.height) {
    // Untangling a pose that clipped: any edit that leaves it clipping less goes through.
    restore(rig, after, null, 0)
    if (selfContacts(rig).depth <= already) return { blocked: null, limited }
  }
  let ok = 0
  let blocked: Contact | null = null
  for (let i = 1; i <= PATH_SAMPLES; i++) {
    const t = i / PATH_SAMPLES
    restore(rig, before, after, t)
    const contacts = selfContacts(rig)
    if (contacts.depth > allowed) {
      blocked = contacts.worst
      break
    }
    ok = t
  }
  if (!blocked) {
    restore(rig, after, null, 0)
    return { blocked: null, limited }
  }
  let lo = ok
  let hi = ok + 1 / PATH_SAMPLES
  for (let i = 0; i < 10; i++) {
    const mid = (lo + hi) / 2
    restore(rig, before, after, mid)
    if (selfContacts(rig).depth <= allowed) lo = mid
    else hi = mid
  }
  restore(rig, before, after, lo)
  return { blocked, limited }
}
