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

const DOWN = new THREE.Vector3(0, -1, 0)
const UP = new THREE.Vector3(0, 1, 0)
const UPRIGHT: ReadonlySet<JointName> = new Set(['torso', 'neck', 'head'])

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
 * Two-bone IK: rotate `root` and `mid` so `end` reaches `target` (or points
 * at it from as far as the limb reaches). The middle joint keeps bending the
 * way it already bends; a straight limb bends toward `pole` (world direction).
 */
export function solveTwoBone(root: THREE.Object3D, mid: THREE.Object3D, end: THREE.Object3D, target: THREE.Vector3, pole: THREE.Vector3): void {
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
  bend.normalize()
  const along = (upper * upper - lower * lower + reach * reach) / (2 * reach)
  const out = Math.sqrt(Math.max(0, upper * upper - along * along))
  const elbowAt = shoulder.clone().add(dir.clone().multiplyScalar(along)).add(bend.multiplyScalar(out))
  aimJoint(root, elbowAt, DOWN)
  aimJoint(mid, shoulder.clone().add(dir.multiplyScalar(reach)), DOWN)
}

/** Drag the body part hanging from `joint` toward `target` (world space). */
export function dragJoint(rig: FigureRig, joint: JointName, target: THREE.Vector3): void {
  const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(rig.root.getWorldQuaternion(new THREE.Quaternion()))
  const j = rig.joints
  if (joint === 'l_wrist' || joint === 'r_wrist') {
    const side = joint[0] as 'l' | 'r'
    // Elbows point down and back, so a raised hand comes up in front.
    const down = new THREE.Vector3(0, -1, 0)
    solveTwoBone(j[`${side}_arm`], j[`${side}_elbow`], j[joint], target, down.add(forward.clone().multiplyScalar(-0.5)))
  } else if (joint === 'l_ankle' || joint === 'r_ankle') {
    const side = joint[0] as 'l' | 'r'
    // Knees bend forward.
    solveTwoBone(j[`${side}_leg`], j[`${side}_knee`], j[joint], target, forward)
  } else {
    aimJoint(j[joint], target, UPRIGHT.has(joint) ? UP : DOWN)
  }
}

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
