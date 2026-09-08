import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { getCharacterAnchors, solveShot, type CharacterAnchors } from './shotSolver'

function anchors(overrides: Partial<CharacterAnchors> = {}): CharacterAnchors {
  return {
    feet: 0,
    hip: 0.9,
    chest: 1.3,
    head: 1.67,
    centerX: 0,
    centerZ: 0,
    height: 1.8,
    facingYaw: 0,
    ...overrides,
  }
}

const base = { elevation: 'eye', composition: 'center', fovDeg: 40, aspect: 16 / 9 } as const

describe('solveShot', () => {
  it('moves the camera closer as the shot gets tighter', () => {
    const wide = solveShot({ ...base, shotSize: 'wide', angle: 'front', anchors: anchors() })
    const closeup = solveShot({ ...base, shotSize: 'closeup', angle: 'front', anchors: anchors() })
    const target = new THREE.Vector3(0, 1, 0)
    expect(wide.position.distanceTo(target)).toBeGreaterThan(closeup.position.distanceTo(target))
  })

  it('places a front shot in front of the character and a back shot behind', () => {
    const front = solveShot({ ...base, shotSize: 'medium', angle: 'front', anchors: anchors() })
    const back = solveShot({ ...base, shotSize: 'medium', angle: 'back', anchors: anchors() })
    expect(front.position.z).toBeGreaterThan(0)
    expect(back.position.z).toBeLessThan(0)
  })

  it('OTS left and right shoulders are mirror images across the facing axis', () => {
    const subject = anchors({ centerZ: 3 })
    const left = solveShot({ ...base, shotSize: 'medium', angle: 'ots', anchors: anchors(), targetAnchors: subject, otsShoulder: 'left' })
    const right = solveShot({ ...base, shotSize: 'medium', angle: 'ots', anchors: anchors(), targetAnchors: subject, otsShoulder: 'right' })
    expect(left.position.x).toBeCloseTo(-right.position.x, 6)
    expect(left.position.z).toBeCloseTo(right.position.z, 6)
    expect(left.position.x).not.toBeCloseTo(0, 3)
    // Both hug the foreground shoulder (behind the character, who faces +z) and look toward the subject.
    expect(left.position.z).toBeLessThan(0)
    expect(left.target.z).toBeGreaterThan(left.position.z)
  })

  it('OTS follows the foreground character as they turn', () => {
    const facingPlusX = anchors({ facingYaw: Math.PI / 2 })
    const solved = solveShot({ ...base, shotSize: 'medium', angle: 'ots', anchors: facingPlusX })
    // Camera sits behind them on -x, looking toward +x.
    expect(solved.position.x).toBeLessThan(0)
    expect(solved.target.x).toBeGreaterThan(solved.position.x)
  })

  it('dutch angle carries roll, other angles do not', () => {
    expect(solveShot({ ...base, shotSize: 'medium', angle: 'dutch', anchors: anchors() }).rollRad).not.toBe(0)
    expect(solveShot({ ...base, shotSize: 'medium', angle: 'profile', anchors: anchors() }).rollRad).toBe(0)
  })

  it('elevation moves the camera vertically', () => {
    const low = solveShot({ ...base, elevation: 'low', shotSize: 'medium', angle: 'front', anchors: anchors() })
    const bird = solveShot({ ...base, elevation: 'bird', shotSize: 'medium', angle: 'front', anchors: anchors() })
    expect(bird.position.y).toBeGreaterThan(low.position.y)
  })

  it('composition offsets shift the aim point sideways', () => {
    const center = solveShot({ ...base, shotSize: 'medium', angle: 'front', anchors: anchors() })
    const leftThird = solveShot({ ...base, composition: 'leftThird', shotSize: 'medium', angle: 'front', anchors: anchors() })
    expect(leftThird.position.distanceTo(center.position)).toBeLessThan(1e-6)
    expect(leftThird.target.x).not.toBeCloseTo(center.target.x, 3)
  })
})

describe('getCharacterAnchors', () => {
  it('derives height and facing from an object', () => {
    const root = new THREE.Group()
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.4, 1.8, 0.3))
    body.position.y = 0.9
    root.add(body)
    root.rotation.y = Math.PI / 2
    const result = getCharacterAnchors(root)
    expect(result.height).toBeCloseTo(1.8, 5)
    expect(result.feet).toBeCloseTo(0, 5)
    expect(result.facingYaw).toBeCloseTo(Math.PI / 2, 5)
    expect(result.chest).toBeGreaterThan(result.hip)
    expect(result.head).toBeGreaterThan(result.chest)
  })
})
