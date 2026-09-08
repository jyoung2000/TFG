import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { buildCameraMove, sampleCameraTrack } from './cameraMotion'

const start = {
  position: new THREE.Vector3(0, 1.6, 4),
  target: new THREE.Vector3(0, 1.3, 0),
  fov: 40,
}

describe('buildCameraMove', () => {
  it('static produces a single keyframe at t=0', () => {
    const keys = buildCameraMove('static', start, 4)
    expect(keys).toHaveLength(1)
    expect(keys[0].time).toBe(0)
    expect(keys[0].transform.position).toEqual([0, 1.6, 4])
  })

  it('push_in ends closer to the subject; pull_out ends farther', () => {
    const push = buildCameraMove('push_in', start, 4)
    const pull = buildCameraMove('pull_out', start, 4)
    const distance = (p: number[]) => new THREE.Vector3(...(p as [number, number, number])).distanceTo(start.target)
    expect(push[1].time).toBe(4)
    expect(distance(push[1].transform.position)).toBeLessThan(distance(push[0].transform.position))
    expect(distance(pull[1].transform.position)).toBeGreaterThan(distance(pull[0].transform.position))
  })

  it('intensity scales the travel distance and is clamped', () => {
    const gentle = buildCameraMove('dolly_right', start, 4, 0.5)
    const strong = buildCameraMove('dolly_right', start, 4, 2)
    const absurd = buildCameraMove('dolly_right', start, 4, 50)
    const travel = (keys: ReturnType<typeof buildCameraMove>) =>
      Math.abs(keys[1].transform.position[0] - keys[0].transform.position[0])
    expect(travel(strong)).toBeCloseTo(travel(gentle) * 4, 6)
    expect(travel(absurd)).toBeCloseTo(travel(gentle) * 6, 6) // clamped to 3×
  })

  it('pans rotate without moving the camera', () => {
    const pan = buildCameraMove('pan_left', start, 3)
    expect(pan[1].transform.position).toEqual(pan[0].transform.position)
    expect(pan[1].transform.rotation[1]).not.toBeCloseTo(pan[0].transform.rotation[1], 3)
  })

  it('enforces a minimum duration for the end key', () => {
    expect(buildCameraMove('push_in', start, 0.1)[1].time).toBe(0.5)
  })
})

describe('sampleCameraTrack', () => {
  const keys = buildCameraMove('push_in', start, 4)

  it('clamps before the first and after the last key', () => {
    expect(sampleCameraTrack(keys, -1)?.position).toEqual(keys[0].transform.position)
    expect(sampleCameraTrack(keys, 99)?.position).toEqual(keys[1].transform.position)
  })

  it('interpolates position linearly at the midpoint', () => {
    const mid = sampleCameraTrack(keys, 2)
    expect(mid).not.toBeNull()
    for (let axis = 0; axis < 3; axis++) {
      const expected = (keys[0].transform.position[axis] + keys[1].transform.position[axis]) / 2
      expect(mid!.position[axis]).toBeCloseTo(expected, 6)
    }
    expect(mid!.fov).toBe(40)
  })

  it('returns null for an empty track and handles a single key', () => {
    expect(sampleCameraTrack([], 1)).toBeNull()
    const single = sampleCameraTrack([keys[0]], 1)
    expect(single?.position).toEqual(keys[0].transform.position)
  })
})
