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
