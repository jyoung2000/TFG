/**
 * Reference underlay for the composer: the analysed frame (or its depth map)
 * behind the shot camera's view, so figures and the camera can be matched to
 * the real shot by eye.
 *
 * The concept follows Blockout's `ReferenceUnderlay` (wassermanproductions/
 * blockout, Apache-2.0 — NOTICE in this folder), which ghosts a reference
 * video over the viewport in sync with the timeline. Here the underlay is a
 * plain three.js plane parented to the shot camera, sized to fill its frustum
 * at a fixed distance, rendered only through the viewfinder (PiP / capture).
 */

import * as THREE from 'three'

export class ReferenceUnderlay {
  readonly mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>
  private texture: THREE.Texture | null = null
  private readonly distance = 60

  constructor(private readonly camera: THREE.PerspectiveCamera) {
    const material = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.55, depthWrite: false, toneMapped: false })
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material)
    this.mesh.position.set(0, 0, -this.distance)
    this.mesh.visible = false
    this.mesh.renderOrder = -10
    this.mesh.userData.underlay = true
    camera.add(this.mesh)
  }

  get visible(): boolean {
    return this.mesh.visible
  }

  set opacity(value: number) {
    this.mesh.material.opacity = Math.max(0, Math.min(1, value))
  }

  get opacity(): number {
    return this.mesh.material.opacity
  }

  /** Fit the plane to the camera frustum at the underlay distance. */
  fit(): void {
    const height = 2 * this.distance * Math.tan((this.camera.fov * Math.PI) / 360)
    this.mesh.scale.set(height * this.camera.aspect, height, 1)
  }

  async load(url: string): Promise<void> {
    const loader = new THREE.TextureLoader()
    const texture = await loader.loadAsync(url)
    texture.colorSpace = THREE.SRGBColorSpace
    this.texture?.dispose()
    this.texture = texture
    this.mesh.material.map = texture
    this.mesh.material.needsUpdate = true
    this.mesh.visible = true
    this.fit()
  }

  clear(): void {
    this.mesh.visible = false
    this.mesh.material.map = null
    this.texture?.dispose()
    this.texture = null
  }

  dispose(): void {
    this.clear()
    this.mesh.geometry.dispose()
    this.mesh.material.dispose()
    this.camera.remove(this.mesh)
  }
}
