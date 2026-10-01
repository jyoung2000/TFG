/**
 * Where a body part is being dragged, drawn in the viewport (asked
 * 2026-10-01: "tell where your dragging"): a dot where the drag began, a line
 * to where the part is now, and the cursor's target - green while the part
 * follows it, red with a dashed gap when the body or a joint stops it. Drawn
 * over everything so it shows through the figure.
 */

import * as THREE from 'three'

const START = '#e4e4e7'
const PATH = '#a78bfa'
const FOLLOWING = '#4ade80'
const STOPPED = '#f87171'

function overlayMaterial<T extends THREE.Material>(material: T): T {
  material.depthTest = false
  material.depthWrite = false
  material.transparent = true
  return material
}

export class DragGuide {
  readonly group = new THREE.Group()
  private startDot: THREE.Mesh
  private targetDot: THREE.Mesh
  private path: THREE.Line
  private gap: THREE.Line
  private targetMaterial: THREE.MeshBasicMaterial

  constructor() {
    const dot = new THREE.SphereGeometry(1, 12, 8)
    this.startDot = new THREE.Mesh(dot, overlayMaterial(new THREE.MeshBasicMaterial({ color: START, opacity: 0.8 })))
    this.startDot.scale.setScalar(0.014)
    this.targetMaterial = overlayMaterial(new THREE.MeshBasicMaterial({ color: FOLLOWING, opacity: 0.9 }))
    this.targetDot = new THREE.Mesh(dot, this.targetMaterial)
    this.targetDot.scale.setScalar(0.018)
    const line = () => new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()])
    this.path = new THREE.Line(line(), overlayMaterial(new THREE.LineBasicMaterial({ color: PATH, opacity: 0.95 })))
    this.gap = new THREE.Line(line(), overlayMaterial(new THREE.LineDashedMaterial({ color: STOPPED, dashSize: 0.02, gapSize: 0.015 })))
    for (const part of [this.startDot, this.targetDot, this.path, this.gap]) {
      part.renderOrder = 30
      part.frustumCulled = false
      this.group.add(part)
    }
    this.group.visible = false
  }

  show(start: THREE.Vector3): void {
    this.startDot.position.copy(start)
    this.update(start, start, false)
    this.group.visible = true
  }

  /** `at`: where the part is; `target`: where the cursor asks it to be. */
  update(at: THREE.Vector3, target: THREE.Vector3, stopped: boolean): void {
    setLine(this.path, this.startDot.position, at)
    setLine(this.gap, at, target)
    this.gap.computeLineDistances()
    this.gap.visible = stopped && at.distanceTo(target) > 0.01
    this.targetDot.position.copy(target)
    this.targetMaterial.color.set(stopped ? STOPPED : FOLLOWING)
  }

  hide(): void {
    this.group.visible = false
  }

  dispose(): void {
    this.startDot.geometry.dispose()
    for (const part of [this.startDot, this.targetDot, this.path, this.gap]) (part.material as THREE.Material).dispose()
    this.path.geometry.dispose()
    this.gap.geometry.dispose()
  }
}

function setLine(line: THREE.Line, a: THREE.Vector3, b: THREE.Vector3): void {
  const position = line.geometry.attributes.position as THREE.BufferAttribute
  position.setXYZ(0, a.x, a.y, a.z)
  position.setXYZ(1, b.x, b.y, b.z)
  position.needsUpdate = true
  line.geometry.computeBoundingSphere()
}
