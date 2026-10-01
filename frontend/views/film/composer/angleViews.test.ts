import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { LORA_ANGLES, angleCamera, type AngleView } from './angleViews'

/* Asked 2026-10-01: the camera must accurately generate multiple angle shots
 * for LoRA training. Each view is checked through a real three.js camera:
 * the framing fits the body as named, and the camera sits on the named side. */

const FIGURE = { position: [1, 0, -2] as [number, number, number], yaw: 0.3, height: 1.7 }
const VFOV = 40

function shoot(view: AngleView) {
  const { position, target } = angleCamera(FIGURE, view, VFOV)
  const camera = new THREE.PerspectiveCamera(VFOV, 3 / 4, 0.05, 200)
  camera.position.set(...position)
  camera.lookAt(new THREE.Vector3(...target))
  camera.updateMatrixWorld()
  const project = (y: number) => new THREE.Vector3(FIGURE.position[0], FIGURE.position[1] + y, FIGURE.position[2]).project(camera)
  return { camera, head: project(FIGURE.height), feet: project(0), waist: project(FIGURE.height * 0.5) }
}

const byName = (name: string) => LORA_ANGLES.find(v => v.name === name)!

describe('angleCamera', () => {
  it('a full shot shows the whole body inside the frame', () => {
    const { head, feet } = shoot(byName('full-front'))
    expect(head.y).toBeLessThan(1)
    expect(feet.y).toBeGreaterThan(-1)
    expect(head.y - feet.y).toBeGreaterThan(1.4) // the body fills most of the 2-unit frame height
  })

  it('a close-up frames the head, with the waist out of the frame', () => {
    const { head, waist } = shoot(byName('closeup-front'))
    expect(head.y).toBeLessThan(1)
    expect(waist.y).toBeLessThan(-1)
  })

  it.each([
    ['full-front', 0],
    ['full-profile-left', 90],
    ['full-back', 180],
    ['full-profile-right', -90],
  ])('%s puts the camera on that side of the figure', (name, yawDeg) => {
    const { position } = angleCamera(FIGURE, byName(name), VFOV)
    const around = FIGURE.yaw + (yawDeg * Math.PI) / 180
    const toCamera = new THREE.Vector2(position[0] - FIGURE.position[0], position[2] - FIGURE.position[2]).normalize()
    expect(toCamera.x).toBeCloseTo(Math.sin(around), 5)
    expect(toCamera.y).toBeCloseTo(Math.cos(around), 5)
  })

  it('a high angle is above, a low angle below', () => {
    const level = angleCamera(FIGURE, byName('full-front'), VFOV).position[1]
    expect(angleCamera(FIGURE, byName('full-high'), VFOV).position[1]).toBeGreaterThan(level + 0.5)
    expect(angleCamera(FIGURE, byName('full-low'), VFOV).position[1]).toBeLessThan(level)
  })

  it('offers a LoRA-sized, varied set with unique names', () => {
    expect(LORA_ANGLES.length).toBeGreaterThanOrEqual(15)
    expect(new Set(LORA_ANGLES.map(v => v.name)).size).toBe(LORA_ANGLES.length)
    expect(new Set(LORA_ANGLES.map(v => v.size))).toEqual(new Set(['full', 'medium', 'closeup']))
  })
})
