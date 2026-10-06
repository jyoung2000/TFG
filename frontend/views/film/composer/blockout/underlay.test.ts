import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { ReferenceUnderlay } from './underlay'

/*
 * MEASURED in the installed app (r21, 2026-10-01): with "Reference frame behind
 * the viewfinder" on and the frame loaded, the viewfinder showed no frame. The
 * composer's fog runs 26-60 m and the plane sat at 60 m, so it rendered as
 * pure fog colour; the 24 m floor (opaque, nearer) also hid its lower half.
 */
describe('ReferenceUnderlay', () => {
  it('is not swallowed by the scene fog', () => {
    const underlay = new ReferenceUnderlay(new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 200))
    expect(underlay.mesh.material.fog).toBe(false)
  })

  it('shows the whole frame, not only what the floor leaves uncovered', () => {
    const underlay = new ReferenceUnderlay(new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 200))
    expect(underlay.mesh.material.depthTest).toBe(false)
    expect(underlay.mesh.material.transparent).toBe(true)
    // Drawn after the scene, so the figures show through it at the set opacity.
    expect(underlay.mesh.renderOrder).toBeGreaterThan(0)
  })
})

/* MEASURED (r24): a 9:16 reproduced portrait filled the 16:9 viewfinder,
 * stretched to twice its width. The solved camera keeps the image's vertical
 * field of view, so the image is fitted to the frame height at its own aspect. */
describe('ReferenceUnderlay fit', () => {
  it('keeps the image aspect: a portrait spans the frame height, not its width', () => {
    const camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 200)
    const underlay = new ReferenceUnderlay(camera)
    underlay.imageAspect = 9 / 16
    underlay.fit()
    const frameHeight = 2 * 60 * Math.tan((40 * Math.PI) / 360)
    expect(underlay.mesh.scale.y).toBeCloseTo(frameHeight, 5)
    expect(underlay.mesh.scale.x / underlay.mesh.scale.y).toBeCloseTo(9 / 16, 5)
  })

  it('fits a wider image to the frame height too, its sides cropped by the viewfinder', () => {
    const camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 200)
    const underlay = new ReferenceUnderlay(camera)
    underlay.imageAspect = 2.16 // the reference clip, 1280 x 592
    underlay.fit()
    const frameHeight = 2 * 60 * Math.tan((40 * Math.PI) / 360)
    expect(underlay.mesh.scale.y).toBeCloseTo(frameHeight, 5)
    expect(underlay.mesh.scale.x / underlay.mesh.scale.y).toBeCloseTo(2.16, 5)
  })
})
