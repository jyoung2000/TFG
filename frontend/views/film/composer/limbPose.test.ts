import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { buildFigure, readPose } from './figure'
import { dragHandle, dragJoint } from './limbPose'

/* Asked 2026-10-01: make the limbs and pose of the model easy to edit. In pose
 * mode a body part follows the cursor; each test drags a part of a real rig
 * and checks where the body ends up. The figure faces +Z; its left is +X. */

const at = (o: THREE.Object3D) => { o.updateWorldMatrix(true, false); return new THREE.Vector3().setFromMatrixPosition(o.matrixWorld) }

function figure() {
  const rig = buildFigure('male', '#e4572e')
  const scene = new THREE.Scene()
  scene.add(rig.root)
  rig.root.position.set(0.5, 0, -2)
  rig.root.rotation.y = 0.4
  rig.root.updateMatrixWorld(true)
  return rig
}

describe('dragging a hand', () => {
  it('puts the wrist where it is dragged, the arm following', () => {
    const rig = figure()
    const shoulder = at(rig.joints.l_arm)
    const target = shoulder.clone().add(new THREE.Vector3(0.15, 0.1, 0.2))
    dragJoint(rig, 'l_wrist', target)
    expect(at(rig.joints.l_wrist).distanceTo(target)).toBeLessThan(0.005)
    // The arm keeps its length (the bones are rotated, not stretched).
    expect(at(rig.joints.l_elbow).distanceTo(shoulder)).toBeCloseTo(0.17 * 1.8, 3)
  })

  it('a hand raised in front keeps the elbow pointing down, like an arm', () => {
    const rig = figure()
    const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(rig.root.quaternion)
    const shoulder = at(rig.joints.r_arm)
    const target = shoulder.clone().add(forward.clone().multiplyScalar(0.2)).add(new THREE.Vector3(0, 0.05, 0))
    dragJoint(rig, 'r_wrist', target)
    expect(at(rig.joints.r_wrist).distanceTo(target)).toBeLessThan(0.005)
    // The elbow sits below the straight line from the shoulder to the hand.
    const elbow = at(rig.joints.r_elbow)
    const t = elbow.clone().sub(shoulder).dot(target.clone().sub(shoulder).normalize())
    const onLine = shoulder.clone().add(target.clone().sub(shoulder).normalize().multiplyScalar(t))
    expect(elbow.y).toBeLessThan(onLine.y - 0.05)
  })

  it('out of reach, the arm points straight at the cursor', () => {
    const rig = figure()
    const shoulder = at(rig.joints.l_arm)
    const target = shoulder.clone().add(new THREE.Vector3(3, 1, 0))
    dragJoint(rig, 'l_wrist', target)
    const reachDir = at(rig.joints.l_wrist).sub(shoulder).normalize()
    expect(reachDir.dot(target.clone().sub(shoulder).normalize())).toBeGreaterThan(0.999)
  })
})

describe('dragging a foot', () => {
  it('lifts the foot with the knee bending forward', () => {
    const rig = figure()
    const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(rig.root.quaternion)
    const hip = at(rig.joints.l_leg)
    const target = at(rig.joints.l_ankle).add(new THREE.Vector3(0, 0.35, 0)).add(forward.clone().multiplyScalar(0.1))
    dragJoint(rig, 'l_ankle', target)
    expect(at(rig.joints.l_ankle).distanceTo(target)).toBeLessThan(0.005)
    expect(at(rig.joints.l_knee).sub(hip).dot(forward)).toBeGreaterThan(0.05)
  })
})

describe('dragging a segment', () => {
  it.each(['l_arm', 'l_elbow', 'r_leg', 'torso', 'neck'] as const)('%s swings to point at the cursor', joint => {
    const rig = figure()
    const pivot = at(rig.joints[joint])
    const target = pivot.clone().add(new THREE.Vector3(0.3, 0.2, 0.25))
    dragJoint(rig, joint, target)
    const pointing = dragHandle(rig, joint).sub(pivot).normalize()
    expect(pointing.dot(target.clone().sub(pivot).normalize())).toBeGreaterThan(0.999)
  })

  it('leaves a pose the figure can save (finite angles)', () => {
    const rig = figure()
    dragJoint(rig, 'l_wrist', at(rig.joints.l_arm).add(new THREE.Vector3(0.1, 0.25, 0.15)))
    dragJoint(rig, 'head', at(rig.joints.head).add(new THREE.Vector3(0.2, 0.3, 0.1)))
    for (const euler of Object.values(readPose(rig))) for (const v of euler) expect(Number.isFinite(v)).toBe(true)
  })
})
