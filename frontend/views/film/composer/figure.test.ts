import { describe, expect, it } from 'vitest'
import { FIGURE_HEIGHTS, JOINT_NAMES, applyPose, buildFigure, jointForObject, mirrorPose, readPose } from './figure'

describe('mirrorPose', () => {
  it('swaps left/right limbs and flips yaw/roll', () => {
    const mirrored = mirrorPose({ l_arm: [10, 20, 30], r_elbow: [5, -5, 15], head: [0, 40, 0] })
    expect(mirrored.r_arm).toEqual([10, -20, -30])
    expect(mirrored.l_elbow).toEqual([5, 5, -15])
    expect(mirrored.head).toEqual([0, -40, -0])
    expect(mirrored.l_arm).toBeUndefined()
  })

  it('is an involution (up to signed zero)', () => {
    const pose = { l_leg: [12, 3, -7] as [number, number, number], torso: [0, 15, 4] as [number, number, number] }
    const twice = mirrorPose(mirrorPose(pose))
    expect(twice.l_leg).toEqual([12, 3, -7])
    expect(twice.torso.map(v => v + 0)).toEqual([0, 15, 4])
  })
})

describe('buildFigure', () => {
  it('builds every named joint at the variant height', () => {
    for (const variant of ['male', 'female', 'child'] as const) {
      const rig = buildFigure(variant, '#ffffff')
      expect(rig.height).toBe(FIGURE_HEIGHTS[variant])
      for (const joint of JOINT_NAMES) expect(rig.joints[joint]).toBeDefined()
      rig.dispose()
    }
  })

  it('round-trips a pose through apply/read', () => {
    const rig = buildFigure('male', '#ffffff')
    applyPose(rig, { l_arm: [0, 0, 45], r_knee: [30, 0, 0] })
    const read = readPose(rig)
    expect(read.l_arm[2]).toBeCloseTo(45, 1)
    expect(read.r_knee[0]).toBeCloseTo(30, 1)
    expect(read.head).toBeUndefined() // zero rotations are omitted
    applyPose(rig, {})
    expect(readPose(rig)).toEqual({})
    rig.dispose()
  })
})

/* Asked 2026-10-01: poses must be easy to edit. In Pose mode a click on a
 * limb picks the joint that limb hangs from, and the rotate gizmo goes there. */
describe('jointForObject', () => {
  it('maps every limb mesh to the joint it hangs from', () => {
    const rig = buildFigure('female', '#e4572e')
    for (const name of JOINT_NAMES) {
      const group = rig.joints[name]
      // Its own meshes, and those in the unnamed segment wrapper a limb hangs in (not child joints).
      const meshes = group.children.flatMap(child => (child.type === 'Mesh' ? [child] : child.name === '' ? child.children.filter(c => c.type === 'Mesh') : []))
      for (const mesh of meshes) expect(jointForObject(mesh)).toBe(name)
    }
  })

  it('a forearm click is the elbow, an upper-arm click the shoulder', () => {
    const rig = buildFigure('male', '#29b6f6')
    const upper = rig.joints.l_arm.children[0].children.find(c => c.type === 'Mesh')!
    const lower = rig.joints.l_elbow.children[0].children.find(c => c.type === 'Mesh')!
    expect(jointForObject(upper)).toBe('l_arm')
    expect(jointForObject(lower)).toBe('l_elbow')
  })

  it('the pelvis belongs to no joint: clicking it moves the whole figure', () => {
    const rig = buildFigure('male', '#29b6f6')
    const pelvisMesh = rig.root.children[0].children.find(c => c.type === 'Mesh')!
    expect(jointForObject(pelvisMesh)).toBeNull()
  })
})
