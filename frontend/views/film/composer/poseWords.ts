/**
 * A posed mannequin in words, for the live pose preview (asked 2026-10-01).
 * Shown only the mannequin, the image model copied the photo's pose; told
 * the edit in words it followed it. Each limb gets a coarse phrase from
 * where its hand or foot sits relative to the body; with the photo's pose as
 * a baseline only the limbs the user changed are named, so the photo's own
 * pose is left to the photo.
 */

import * as THREE from 'three'
import type { Vec3 } from '../../../types/film'
import { applyPose, buildFigure, type FigureRig } from './figure'

/** How the figure faces the shot camera: decides which side of the picture its left is on. */
export type Facing = 'camera' | 'away' | 'side'

type Limb = 'l_arm' | 'r_arm' | 'l_leg' | 'r_leg'
const LIMBS: Limb[] = ['l_arm', 'r_arm', 'l_leg', 'r_leg']
const REST: Record<Limb, string> = {
  l_arm: 'hanging relaxed at the side',
  r_arm: 'hanging relaxed at the side',
  l_leg: 'straight, the foot on the ground',
  r_leg: 'straight, the foot on the ground',
}

function inFigure(rig: FigureRig, joint: THREE.Object3D): THREE.Vector3 {
  joint.updateWorldMatrix(true, false)
  const world = new THREE.Vector3().setFromMatrixPosition(joint.matrixWorld)
  return rig.root.worldToLocal(world)
}

function armPhrase(rig: FigureRig, side: 'l' | 'r'): string {
  const H = rig.height
  const sign = side === 'l' ? 1 : -1
  const shoulder = inFigure(rig, rig.joints[`${side}_arm`])
  const elbow = inFigure(rig, rig.joints[`${side}_elbow`])
  const hand = inFigure(rig, rig.joints[`${side}_wrist`])
  const head = inFigure(rig, rig.joints.head).add(new THREE.Vector3(0, 0.07 * H, 0))
  const up = hand.y - shoulder.y
  const out = sign * (hand.x - shoulder.x)
  const forward = hand.z - shoulder.z
  if (hand.distanceTo(head) < 0.1 * H) return 'with the hand on the head'
  // Folded up: the hand by the shoulder, the elbow down (not an arm held out).
  if (hand.distanceTo(shoulder) < 0.12 * H && elbow.y < shoulder.y - 0.06 * H) return 'bent up, the hand at the shoulder'
  if (up > 0.12 * H) {
    if (out > 0.15 * H) return 'raised up and out to the side'
    if (forward > 0.15 * H) return 'raised up and forward'
    return 'raised straight up above the head'
  }
  if (up > -0.08 * H) return out >= forward ? 'stretched out to the side at shoulder height' : 'reaching forward at shoulder height'
  const hipY = 0.52 * H
  if (Math.abs(hand.y - hipY) < 0.09 * H && sign * (elbow.x - shoulder.x) > 0.06 * H) return 'with the hand on the hip'
  if (forward > 0.1 * H) return 'bent, the hand in front of the body'
  if (out > 0.15 * H) return 'held out away from the body'
  return ''
}

function legPhrase(rig: FigureRig, side: 'l' | 'r'): string {
  const H = rig.height
  const sign = side === 'l' ? 1 : -1
  const hip = inFigure(rig, rig.joints[`${side}_leg`])
  const knee = inFigure(rig, rig.joints[`${side}_knee`])
  const foot = inFigure(rig, rig.joints[`${side}_ankle`])
  if (foot.y > 0.1 * H) {
    if (knee.y > hip.y - 0.15 * H && knee.z > hip.z) return 'lifted with the knee raised'
    if (foot.z < hip.z - 0.08 * H) return 'bent back, the foot lifted behind'
    if (sign * (foot.x - hip.x) > 0.15 * H) return 'lifted out to the side'
    return 'with the foot lifted off the ground'
  }
  const forward = foot.z - hip.z
  if (forward > 0.12 * H) return 'stepping forward'
  if (forward < -0.12 * H) return 'stepping back'
  if (sign * (foot.x - hip.x) > 0.12 * H) return 'stepping out to the side'
  return ''
}

function phrases(rig: FigureRig): Record<Limb, string> {
  rig.root.updateMatrixWorld(true)
  return { l_arm: armPhrase(rig, 'l'), r_arm: armPhrase(rig, 'r'), l_leg: legPhrase(rig, 'l'), r_leg: legPhrase(rig, 'r') }
}

/** The baseline pose on a scratch rig the same size as `rig`. */
function baselinePhrases(rig: FigureRig, pose: Record<string, Vec3>): Record<Limb, string> {
  const variant = rig.height <= 1.3 ? 'child' : rig.height < 1.7 ? 'female' : 'male'
  const scratch = buildFigure(variant, '#000000')
  try {
    applyPose(scratch, pose)
    return phrases(scratch)
  } finally {
    scratch.dispose()
  }
}

function limbName(limb: Limb, facing: Facing): string {
  const left = limb.startsWith('l_')
  const part = `${left ? 'left' : 'right'} ${limb.endsWith('arm') ? 'arm' : 'leg'}`
  if (facing === 'side') return part
  // Facing the camera the figure's left is on the right of the picture.
  const pictureSide = (facing === 'camera') === left ? 'right' : 'left'
  return `${part} (on the ${pictureSide} side of the picture)`
}

/**
 * The pose of `rig` in words, e.g. "the person's left arm (on the right side
 * of the picture) raised straight up above the head". With `baseline` (the
 * photo's pose) only the limbs that differ from it are named; '' when none.
 */
export function poseWords(rig: FigureRig, baseline: Record<string, Vec3> | null, facing: Facing): string {
  const now = phrases(rig)
  const before = baseline ? baselinePhrases(rig, baseline) : null
  const parts: string[] = []
  for (const limb of LIMBS) {
    if (before ? now[limb] === before[limb] : !now[limb]) continue
    parts.push(`the person's ${limbName(limb, facing)} ${now[limb] || REST[limb]}`)
  }
  return parts.join(', ')
}
