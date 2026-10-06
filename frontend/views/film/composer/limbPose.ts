/**
 * Posing by dragging (asked 2026-10-01: make the limbs and pose of the model
 * easy to edit). In the composer's pose mode a body part follows the cursor:
 *
 *   - a hand or a foot goes where it is dragged; the arm / leg solves for it
 *     (two-bone IK), the elbow bending back and the knee forward, like a body;
 *   - any other part swings from its joint to point at the cursor
 *     (an upper arm from the shoulder, a forearm from the elbow, the torso
 *     from the hips, the head from the neck).
 *
 * Works on the rig from `figure.ts`: limbs hang along -Y from their joint,
 * the torso, neck and head rise along +Y, and the figure faces +Z.
 */

import * as THREE from 'three'
import type { FigureRig, JointName } from './figure'
import { selfContacts } from './anatomy'

const DOWN = new THREE.Vector3(0, -1, 0)
const UP = new THREE.Vector3(0, 1, 0)
const UPRIGHT: ReadonlySet<JointName> = new Set(['torso', 'neck', 'head'])
/** The side a hinge folds toward, in its parent limb's space: forearms fold to the front, shins to the back. */
const ELBOW_FLEX = new THREE.Vector3(0, 0, 1)
const KNEE_FLEX = new THREE.Vector3(0, 0, -1)

function worldPosition(object: THREE.Object3D): THREE.Vector3 {
  object.updateWorldMatrix(true, false)
  return new THREE.Vector3().setFromMatrixPosition(object.matrixWorld)
}

/** Turn `joint` (the least rotation) so its segment - `axis` in its own space - points at `target`. */
export function aimJoint(joint: THREE.Object3D, target: THREE.Vector3, axis: THREE.Vector3): void {
  const origin = worldPosition(joint)
  const want = target.clone().sub(origin)
  if (want.lengthSq() < 1e-8) return
  want.normalize()
  const worldQuat = joint.getWorldQuaternion(new THREE.Quaternion())
  const have = axis.clone().applyQuaternion(worldQuat).normalize()
  const delta = new THREE.Quaternion().setFromUnitVectors(have, want)
  const parentQuat = joint.parent ? joint.parent.getWorldQuaternion(new THREE.Quaternion()) : new THREE.Quaternion()
  joint.quaternion.copy(parentQuat.invert().multiply(delta.multiply(worldQuat)))
  joint.updateWorldMatrix(false, true)
}

/**
 * Bend a hinge (an elbow, a knee) so the segment below `mid` points along
 * `direction` (world), as a body does it: the limb above turns about its own
 * length (the upper arm / thigh rotates) until the hinge's folding side
 * `flex` (in `root`'s space: +Z for an elbow, which folds the forearm to the
 * front, -Z for a knee) faces the way the segment must go, then the hinge
 * bends about its own X axis only. Its twist (Y) is kept; it never bends
 * sideways.
 */
export function bendHinge(root: THREE.Object3D, mid: THREE.Object3D, direction: THREE.Vector3, flex: THREE.Vector3): void {
  const want = direction.clone().normalize()
  const rootQuat = root.getWorldQuaternion(new THREE.Quaternion())
  const bone = DOWN.clone().applyQuaternion(rootQuat).normalize()
  const side = want.clone().sub(bone.clone().multiplyScalar(want.dot(bone)))
  if (side.lengthSq() > 1e-8) {
    side.normalize()
    const facing = flex.clone().applyQuaternion(rootQuat)
    facing.sub(bone.clone().multiplyScalar(facing.dot(bone)))
    if (facing.lengthSq() > 1e-8) {
      facing.normalize()
      const angle = Math.atan2(bone.dot(facing.clone().cross(side)), facing.dot(side))
      const turn = new THREE.Quaternion().setFromAxisAngle(bone, angle)
      const parentQuat = root.parent ? root.parent.getWorldQuaternion(new THREE.Quaternion()) : new THREE.Quaternion()
      root.quaternion.copy(parentQuat.invert().multiply(turn.multiply(rootQuat)))
      root.updateWorldMatrix(false, true)
    }
  }
  const fold = Math.acos(THREE.MathUtils.clamp(bone.dot(want), -1, 1))
  const twist = mid.rotation.y
  mid.rotation.set(flex.z > 0 ? -fold : fold, twist, 0, 'XYZ')
  mid.updateWorldMatrix(false, true)
}

/**
 * Two-bone IK: rotate `root` and `mid` so `end` reaches `target` (or points
 * at it from as far as the limb reaches). The middle joint keeps bending the
 * way it already bends; a straight limb bends toward `pole` (world direction).
 * With `flex` the middle joint is a hinge (see `bendHinge`). `turn` swings
 * the bend that many radians round the reach (the elbow rises out, or drops).
 */
export function solveTwoBone(root: THREE.Object3D, mid: THREE.Object3D, end: THREE.Object3D, target: THREE.Vector3, pole: THREE.Vector3, flex?: THREE.Vector3, turn = 0): void {
  const shoulder = worldPosition(root)
  const elbow = worldPosition(mid)
  const wrist = worldPosition(end)
  const upper = shoulder.distanceTo(elbow)
  const lower = elbow.distanceTo(wrist)
  const toTarget = target.clone().sub(shoulder)
  const raw = toTarget.length()
  if (raw < 1e-6 || upper < 1e-6 || lower < 1e-6) return
  const dir = toTarget.normalize()
  const reach = Math.min(Math.max(raw, Math.abs(upper - lower) + 1e-4), upper + lower - 1e-4)
  // Which way the limb bends now: the middle joint's offset from its own
  // root→end line. A straight limb has none and bends the natural way (`pole`).
  const limb = wrist.clone().sub(shoulder).normalize()
  const current = elbow.clone().sub(shoulder)
  current.sub(limb.clone().multiplyScalar(current.dot(limb)))
  const bend = current.lengthSq() > 1e-4 ? current : pole.clone()
  bend.sub(dir.clone().multiplyScalar(bend.dot(dir)))
  if (bend.lengthSq() < 1e-8) {
    // The bend direction lies along the reach: fall back to a sideways one.
    bend.copy(new THREE.Vector3(1, 0, 0)).sub(dir.clone().multiplyScalar(dir.x))
  }
  if (turn) bend.applyAxisAngle(dir, turn)
  bend.normalize()
  const along = (upper * upper - lower * lower + reach * reach) / (2 * reach)
  const out = Math.sqrt(Math.max(0, upper * upper - along * along))
  const elbowAt = shoulder.clone().add(dir.clone().multiplyScalar(along)).add(bend.multiplyScalar(out))
  aimJoint(root, elbowAt, DOWN)
  const wristAt = shoulder.clone().add(dir.multiplyScalar(reach))
  if (flex) bendHinge(root, mid, wristAt.sub(elbowAt), flex)
  else aimJoint(mid, wristAt, DOWN)
}

/** Drag the body part hanging from `joint` toward `target` (world space). */
export function dragJoint(rig: FigureRig, joint: JointName, target: THREE.Vector3): void {
  const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(rig.root.getWorldQuaternion(new THREE.Quaternion()))
  const j = rig.joints
  if (joint === 'l_wrist' || joint === 'r_wrist') {
    const side = joint[0] as 'l' | 'r'
    // Elbows point down, back and a little out, so a raised hand comes up in
    // front and a hand brought to the chest keeps the forearm off the body.
    const outward = new THREE.Vector3(side === 'l' ? 1 : -1, 0, 0).applyQuaternion(rig.root.getWorldQuaternion(new THREE.Quaternion()))
    const pole = new THREE.Vector3(0, -1, 0).add(forward.clone().multiplyScalar(-0.5)).add(outward.multiplyScalar(0.15))
    reachClear(rig, j[`${side}_arm`], j[`${side}_elbow`], j[joint], turn => solveTwoBone(j[`${side}_arm`], j[`${side}_elbow`], j[joint], target, pole, ELBOW_FLEX, turn))
  } else if (joint === 'l_ankle' || joint === 'r_ankle') {
    const side = joint[0] as 'l' | 'r'
    // Knees bend forward.
    reachClear(rig, j[`${side}_leg`], j[`${side}_knee`], j[joint], turn => solveTwoBone(j[`${side}_leg`], j[`${side}_knee`], j[joint], target, forward, KNEE_FLEX, turn))
  } else if (joint === 'l_elbow' || joint === 'r_elbow') {
    // A forearm swings by the upper arm turning and the elbow folding.
    bendHinge(j[`${joint[0] as 'l' | 'r'}_arm`], j[joint], target.clone().sub(worldPosition(j[joint])), ELBOW_FLEX)
  } else if (joint === 'l_knee' || joint === 'r_knee') {
    bendHinge(j[`${joint[0] as 'l' | 'r'}_leg`], j[joint], target.clone().sub(worldPosition(j[joint])), KNEE_FLEX)
  } else {
    aimJoint(j[joint], target, UPRIGHT.has(joint) ? UP : DOWN)
  }
}

/** Bend-plane swings tried, nearest first, when the natural bend would clip (30° steps). */
const TURNS = [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6].map(k => (k * Math.PI) / 6)

/**
 * Reach with a limb as a body would: the natural bend first; if that pushes
 * the limb into the body (a hand into the thigh as it rises, an upper arm
 * into the ribs as the hand comes to the chest) the elbow or knee swings
 * round the reach - out, up, down - to the nearest bend that stays clear
 * (MEASURED r38: raising a hand from the side caught it on the thigh). The
 * way there must be clear too, not just the end: past the shoulder a coarse
 * drag flipped the bend through the chest and stuck there (MEASURED r39).
 */
function reachClear(rig: FigureRig, root: THREE.Object3D, mid: THREE.Object3D, end: THREE.Object3D, solve: (turn: number) => void): void {
  const start = [root.quaternion.clone(), mid.quaternion.clone()]
  const handBefore = worldPosition(end)
  const place = (q0: THREE.Quaternion, q1: THREE.Quaternion) => {
    root.quaternion.copy(q0)
    mid.quaternion.copy(q1)
    root.updateWorldMatrix(false, true)
  }
  const allowed = Math.max(selfContacts(rig).depth, CLEAR * rig.height)
  /** Solve with `turn`; the worst overlap at the end and on the way there. Leaves the solution in place. */
  const attempt = (turn: number): number => {
    place(start[0], start[1])
    solve(turn)
    const solved = [root.quaternion.clone(), mid.quaternion.clone()]
    let worst = selfContacts(rig).depth
    for (let i = 1; i < PATH_SAMPLES && worst <= allowed; i++) {
      const t = i / PATH_SAMPLES
      place(start[0].clone().slerp(solved[0], t), start[1].clone().slerp(solved[1], t))
      worst = Math.max(worst, selfContacts(rig).depth)
    }
    place(solved[0], solved[1])
    return worst
  }
  let best = 0
  let bestWorst = attempt(0)
  if (bestWorst <= allowed) return
  for (const turn of TURNS) {
    const worst = attempt(turn)
    // An alternative bend may not carry the hand round the body in one move
    // (MEASURED: dragged through the chest, it hopped round to the back).
    // The natural bend is exempt - it is where the hand goes.
    if (worldPosition(end).distanceTo(handBefore) > MAX_HOP * rig.height) continue
    if (worst < bestWorst - 1e-9) {
      best = turn
      bestWorst = worst
      if (worst <= allowed) return
    }
  }
  attempt(best)
}

/** Points checked on the way from the old pose to a new one (as in `constrainPose`). */
const PATH_SAMPLES = 8
/** The furthest (× height) an alternative bend may carry the hand or foot in one move. */
const MAX_HOP = 0.12

/** Overlap (× height) that counts as touching, not clipping - as in `anatomy.ts`. */
const CLEAR = 0.002

/** Where the dragged part is now (the point the cursor holds on to). */
export function dragHandle(rig: FigureRig, joint: JointName): THREE.Vector3 {
  const j = rig.joints
  const end: Partial<Record<JointName, THREE.Object3D>> = {
    l_arm: j.l_elbow, r_arm: j.r_elbow, l_elbow: j.l_wrist, r_elbow: j.r_wrist,
    l_leg: j.l_knee, r_leg: j.r_knee, l_knee: j.l_ankle, r_knee: j.r_ankle,
    torso: j.neck, neck: j.head,
  }
  return worldPosition(end[joint] ?? j[joint])
}
