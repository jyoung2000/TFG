import { describe, expect, it } from 'vitest'
import { FIGURE_HEIGHTS, JOINT_NAMES, applyPose, buildFigure, mirrorPose, readPose } from './figure'

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
