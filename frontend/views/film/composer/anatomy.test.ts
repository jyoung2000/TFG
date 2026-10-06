import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { BODY_SHAPES, constrainPose, selfContacts, snapshotPose } from './anatomy'
import { applyPose, buildFigure, sectionMeshes, type FigureRig } from './figure'
import { dragJoint } from './limbPose'

/* Asked 2026-10-01: "ensure the models have real anatomy and the models
 * can't clip into themselves, i shouldnt be able to drag the arm through the
 * chest". Every test poses a real rig; the figure faces +Z, its left is +X. */

const VARIANTS = ['male', 'female', 'child'] as const

function figure(variant: (typeof VARIANTS)[number] = 'female') {
  const rig = buildFigure(variant, '#e4572e')
  new THREE.Scene().add(rig.root)
  rig.root.position.set(0.4, 0, -1.5)
  rig.root.rotation.y = 0.5
  rig.root.updateMatrixWorld(true)
  return rig
}

const at = (o: THREE.Object3D) => { o.updateWorldMatrix(true, false); return new THREE.Vector3().setFromMatrixPosition(o.matrixWorld) }
const local = (rig: FigureRig, x: number, y: number, z: number) => rig.root.localToWorld(new THREE.Vector3(x * rig.height, y * rig.height, z * rig.height))
const inFigure = (rig: FigureRig, o: THREE.Object3D) => rig.root.worldToLocal(at(o))
const clean = (rig: FigureRig) => selfContacts(rig).depth <= 0.002 * rig.height

/** Drag a joint the way the composer does: one constrained step per pointer move. */
function dragAlong(rig: FigureRig, joint: Parameters<typeof dragJoint>[1], from: THREE.Vector3, to: THREE.Vector3, steps = 24) {
  let blocked = null
  for (let i = 1; i <= steps; i++) {
    const before = snapshotPose(rig)
    dragJoint(rig, joint, from.clone().lerp(to, i / steps))
    const result = constrainPose(rig, before)
    blocked ??= result.blocked
    expect(clean(rig)).toBe(true)
  }
  return blocked
}

describe('a body that does not pass through itself', () => {
  it.each(VARIANTS)('%s: standing at rest touches nothing', variant => {
    expect(selfContacts(figure(variant)).depth).toBe(0)
  })

  it.each(VARIANTS)('%s: natural poses are not mistaken for clipping', variant => {
    const poses: [Parameters<typeof dragJoint>[1], number, number, number][] = [
      ['l_wrist', 0.12, 1.05, 0.02], // hand raised over the head
      ['r_wrist', -0.42, 0.78, 0], // arm out to the side (within reach)
      ['l_ankle', 0.06, 0.3, 0.2], // knee raised
      ['r_wrist', -0.04, 0.68, 0.15], // hand held in front of the chest
    ]
    for (const [joint, x, y, z] of poses) {
      const rig = figure(variant)
      // Reached the way the editor does it: a drag, in small moves.
      const from = at(rig.joints[joint])
      const to = local(rig, x, y, z)
      for (let i = 1; i <= 16; i++) dragJoint(rig, joint, from.clone().lerp(to, i / 16))
      expect(at(rig.joints[joint]).distanceTo(to), `${variant} ${joint}`).toBeLessThan(0.01)
      expect(selfContacts(rig).worst, `${variant} ${joint}`).toBeNull()
    }
  })

  // Live in r38: the green arrow raised a hand from the side; the hand caught
  // on the thigh at once, stuck, then jumped.
  it.each([
    // up the front of the shoulder (through the shoulder itself would fold the elbow past 150°)
    ['straight up', 0, 0.5, 0.2],
    // (each path stays within the arm's reach, 0.32 x height from the shoulder)
    ['out to the side', 0.25, 0.15, 0],
    ['forward', 0, 0.22, 0.28],
  ] as const)('a hand dragged %s from rest follows all the way, catching on nothing', (_, x, y, z) => {
    for (const variant of VARIANTS) {
      const rig = figure(variant)
      const start = at(rig.joints.l_wrist)
      const step = rig.root.localToWorld(new THREE.Vector3(x, y, z).multiplyScalar(rig.height)).sub(rig.root.localToWorld(new THREE.Vector3()))
      for (let i = 1; i <= 30; i++) {
        const target = start.clone().addScaledVector(step, i / 30)
        const before = snapshotPose(rig)
        dragJoint(rig, 'l_wrist', target)
        const { blocked } = constrainPose(rig, before)
        expect(blocked, `${variant} step ${i}`).toBeNull()
        expect(at(rig.joints.l_wrist).distanceTo(target), `${variant} step ${i}`).toBeLessThan(0.01)
      }
    }
  })

  // Live in r39: the green arrow drags the hand straight up the line through
  // the shoulder, ~5 cm per mouse move; at the shoulder the arm flipped its
  // bend through the chest, was stopped, and stayed stuck.
  it.each(VARIANTS)('%s: a hand dragged straight up past the shoulder in coarse steps keeps going', variant => {
    const rig = figure(variant)
    const start = at(rig.joints.l_wrist)
    const up = rig.root.localToWorld(new THREE.Vector3(0, 0.6 * rig.height, 0)).sub(rig.root.localToWorld(new THREE.Vector3()))
    let target = start
    for (let i = 1; i <= 12; i++) {
      target = start.clone().addScaledVector(up, i / 12)
      const before = snapshotPose(rig)
      dragJoint(rig, 'l_wrist', target)
      expect(constrainPose(rig, before).blocked, `step ${i}`).toBeNull()
    }
    expect(at(rig.joints.l_wrist).distanceTo(target)).toBeLessThan(0.01)
  })

  it('a hand dragged through the chest stops at it', () => {
    const rig = figure('female')
    // Start in front of the chest, drag straight back through the body.
    const front = local(rig, 0.02, 0.7, 0.3)
    dragJoint(rig, 'l_wrist', front)
    expect(clean(rig)).toBe(true)
    const blocked = dragAlong(rig, 'l_wrist', front, local(rig, 0.02, 0.7, -0.3))
    expect(blocked?.b).toBe('chest')
    // The hand never got through: it is still in front of the body.
    expect(inFigure(rig, rig.joints.l_wrist).z).toBeGreaterThan(0.03 * rig.height)
  })

  it('an arm swung across the body by its shoulder stops at the chest', () => {
    const rig = figure('male')
    const before = snapshotPose(rig)
    rig.joints.l_arm.rotation.set(0, 0, THREE.MathUtils.degToRad(-100))
    const result = constrainPose(rig, before)
    expect(result.blocked).not.toBeNull()
    expect(clean(rig)).toBe(true)
    expect(THREE.MathUtils.radToDeg(rig.joints.l_arm.rotation.z)).toBeGreaterThan(-90)
  })

  it('a pose that already clips does not trap the limb: moving out is allowed', () => {
    const rig = figure('male')
    applyPose(rig, { l_arm: [0, 0, -95] })
    expect(clean(rig)).toBe(false)
    const before = snapshotPose(rig)
    rig.joints.l_arm.rotation.set(0, 0, THREE.MathUtils.degToRad(15))
    expect(constrainPose(rig, before).blocked).toBeNull()
    expect(THREE.MathUtils.radToDeg(rig.joints.l_arm.rotation.z)).toBeCloseTo(15, 3)
  })
})

describe('joints that bend like a body', () => {
  it('an elbow does not bend backwards, a knee does not bend forwards', () => {
    const rig = figure('male')
    const before = snapshotPose(rig)
    rig.joints.l_elbow.rotation.set(THREE.MathUtils.degToRad(60), 0, 0)
    rig.joints.r_knee.rotation.set(THREE.MathUtils.degToRad(-60), 0, 0)
    const result = constrainPose(rig, before)
    expect(result.limited).toEqual(expect.arrayContaining(['l_elbow', 'r_knee']))
    expect(THREE.MathUtils.radToDeg(rig.joints.l_elbow.rotation.x)).toBeLessThanOrEqual(5.001)
    expect(THREE.MathUtils.radToDeg(rig.joints.r_knee.rotation.x)).toBeGreaterThanOrEqual(-5.001)
  })

  it('a head turns only so far', () => {
    const rig = figure('male')
    const before = snapshotPose(rig)
    rig.joints.head.rotation.set(0, THREE.MathUtils.degToRad(170), 0)
    constrainPose(rig, before)
    expect(Math.abs(THREE.MathUtils.radToDeg(rig.joints.head.rotation.y))).toBeLessThanOrEqual(60.001)
  })

  it('dragging a hand bends the elbow as a hinge: the forearm folds forward, never sideways', () => {
    const rig = figure('male')
    for (const target of [local(rig, 0.25, 0.75, 0.2), local(rig, 0.05, 0.95, 0.1), local(rig, 0.35, 0.55, 0.05)]) {
      dragJoint(rig, 'l_wrist', target)
      expect(at(rig.joints.l_wrist).distanceTo(target)).toBeLessThan(0.005)
      const elbow = rig.joints.l_elbow.rotation
      expect(THREE.MathUtils.radToDeg(elbow.x)).toBeLessThan(0)
      expect(Math.abs(THREE.MathUtils.radToDeg(elbow.z))).toBeLessThan(0.5)
    }
  })

  it('dragging a foot bends the knee as a hinge: the shin folds back', () => {
    const rig = figure('female')
    const target = local(rig, 0.06, 0.25, 0.12)
    dragJoint(rig, 'l_ankle', target)
    expect(at(rig.joints.l_ankle).distanceTo(target)).toBeLessThan(0.005)
    expect(THREE.MathUtils.radToDeg(rig.joints.l_knee.rotation.x)).toBeGreaterThan(0)
    expect(Math.abs(THREE.MathUtils.radToDeg(rig.joints.l_knee.rotation.z))).toBeLessThan(0.5)
  })
})

describe('an anatomical body', () => {
  it.each(VARIANTS)('%s: a waist narrower than the chest and the hips', variant => {
    const shape = BODY_SHAPES[variant]
    const waist = Math.min(...shape.torso.filter(r => r.y > 0.1 && r.y < 0.5).map(r => r.rx))
    const chest = Math.max(...shape.torso.filter(r => r.y > 0.5).map(r => r.rx))
    const hips = Math.max(...shape.pelvis.map(r => r.rx))
    expect(waist).toBeLessThan(chest)
    expect(waist).toBeLessThan(hips)
  })

  it('limbs taper from the shoulder and hip toward the wrist and ankle', () => {
    for (const taper of [BODY_SHAPES.male.upperArm, BODY_SHAPES.male.forearm, BODY_SHAPES.male.thigh, BODY_SHAPES.male.shin]) {
      expect(taper[taper.length - 1][1]).toBeLessThan(Math.max(...taper.map(([, r]) => r)))
    }
  })

  it('hands have a palm, four fingers and a thumb', () => {
    const rig = buildFigure('female', '#ffffff')
    expect(sectionMeshes(rig, 'l_wrist')).toHaveLength(6)
  })
})
