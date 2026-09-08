/**
 * Imperative three.js scene manager for the Shot Composer.
 *
 * Owns the renderer, editor camera (orbit), shot camera (the cinematic
 * camera), object lifecycle (figures/primitives), selection, the transform
 * gizmo, ground-plane dragging, the picture-in-picture viewfinder, capture,
 * keyframes and motion preview. React components drive it through methods
 * and read back via callbacks; during a session the three.js graph is the
 * working state, serialized to a CompositionScene on save/capture.
 *
 * Viewport interaction model (orbit editor camera + raycast select + PiP
 * viewfinder + preserveDrawingBuffer capture + TransformControls gizmo)
 * adapted from Open Media's ComposerViewport / TransformGizmo (MIT; see
 * docs/INTEGRATED_UPSTREAMS.md), rebuilt in plain three.js for React 18.
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js'
import type {
  CameraMove,
  CompositionKeyframe,
  CompositionObject,
  CompositionScene,
  FigureVariant,
  ShotFraming,
  Vec3,
} from '../../../types/film'
import { buildCameraMove, sampleCameraTrack } from './cameraMotion'
import { applyPose, buildFigure, readPose, type FigureRig } from './figure'
import { applySolvedShot, getCharacterAnchors, solveShot } from './shotSolver'

const FIGURE_COLORS = ['#7f9cc4', '#c4907f', '#8fc47f', '#b98fc4', '#c4b97f', '#7fc4b9']

export const SHOT_CAMERA_ID = 'shot-camera'

export type GizmoMode = 'translate' | 'rotate' | 'scale'

export interface ComposerEntity {
  data: CompositionObject
  node: THREE.Object3D
  rig: FigureRig | null
}

export interface TransformSnapshot {
  position: Vec3
  rotation: Vec3
  scale: Vec3
}

interface PrimitiveSpec {
  geometry: () => THREE.BufferGeometry
  y: number
}

const PRIMITIVES: Record<string, PrimitiveSpec> = {
  cube: { geometry: () => new THREE.BoxGeometry(0.6, 0.6, 0.6), y: 0.3 },
  plane: { geometry: () => new THREE.BoxGeometry(1.6, 0.04, 1.6), y: 0.02 },
  cylinder: { geometry: () => new THREE.CylinderGeometry(0.3, 0.3, 0.9, 20), y: 0.45 },
  sphere: { geometry: () => new THREE.SphereGeometry(0.35, 20, 16), y: 0.35 },
  cone: { geometry: () => new THREE.ConeGeometry(0.35, 0.8, 20), y: 0.4 },
}

const newKeyframeId = () => `kf-${Math.random().toString(36).slice(2, 10)}`

export class ComposerScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private editorCamera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private gizmo: TransformControls
  readonly shotCamera: THREE.PerspectiveCamera
  private cameraHelper: THREE.CameraHelper
  private entities = new Map<string, ComposerEntity>()
  private canvas: HTMLCanvasElement
  private raycaster = new THREE.Raycaster()
  private groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  private animationFrame = 0
  private disposed = false
  private selectedId: string | null = null
  private selectionRing: THREE.Mesh
  private dragging: { id: string; offset: THREE.Vector3 } | null = null
  private pointerDownAt: { x: number; y: number } | null = null
  private disposables: { dispose: () => void }[] = []
  private gizmoModeValue: GizmoMode = 'translate'

  /** Camera keyframes for motion preview / hand-authored camera animation. */
  cameraKeyframes: CompositionKeyframe[] = []
  private previewTime: number | null = null
  /** Live transforms captured when a preview scrub starts, restored when it ends. */
  private liveTransforms: Map<string, TransformSnapshot> | null = null
  private liveCamera: { position: Vec3; rotation: Vec3; fov: number } | null = null

  onSelect: (id: string | null) => void = () => {}
  /** Any object transform/pose changed (gizmo, drag, sliders, keyframes). */
  onTransformChange: () => void = () => {}
  /** The shot camera was moved by hand (gizmo / numeric input) → manual mode. */
  onCameraManualChange: () => void = () => {}

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap

    this.scene.background = new THREE.Color('#16181d')
    this.scene.fog = new THREE.Fog('#16181d', 26, 60)

    this.editorCamera = new THREE.PerspectiveCamera(50, 16 / 9, 0.05, 200)
    this.editorCamera.position.set(4.2, 2.6, 5.4)

    this.shotCamera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 200)
    this.shotCamera.position.set(0, 1.6, 4)
    this.shotCamera.name = SHOT_CAMERA_ID
    this.scene.add(this.shotCamera)
    this.cameraHelper = new THREE.CameraHelper(this.shotCamera)
    this.cameraHelper.visible = true
    this.scene.add(this.cameraHelper)

    this.controls = new OrbitControls(this.editorCamera, canvas)
    this.controls.target.set(0, 1, 0)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.maxPolarAngle = Math.PI * 0.55
    this.controls.minDistance = 0.6
    this.controls.maxDistance = 40

    // Transform gizmo (translate / rotate / scale) on the selected object or the shot camera.
    this.gizmo = new TransformControls(this.editorCamera, canvas)
    this.gizmo.setSize(0.8)
    this.gizmo.addEventListener('dragging-changed', event => {
      this.controls.enabled = !(event as unknown as { value: boolean }).value
    })
    this.gizmo.addEventListener('objectChange', () => {
      const target = this.gizmo.object
      if (!target) return
      if (target === this.shotCamera) {
        this.cameraHelper.update()
        this.onCameraManualChange()
        return
      }
      const id = target.userData.entityId as string | undefined
      const entity = id ? this.entities.get(id) : null
      if (entity?.data.type === 'figure') {
        // Figures stay on the floor and upright; scale stays uniform.
        target.position.y = 0
        target.rotation.x = 0
        target.rotation.z = 0
        const uniform = target.scale.y
        target.scale.set(uniform, uniform, uniform)
      }
      this.onTransformChange()
    })
    this.scene.add(this.gizmo.getHelper())

    // Lights
    const hemisphere = new THREE.HemisphereLight('#cfd8e8', '#20222a', 0.9)
    this.scene.add(hemisphere)
    const key = new THREE.DirectionalLight('#ffffff', 2.2)
    key.position.set(5, 8, 4)
    key.castShadow = true
    key.shadow.mapSize.set(1024, 1024)
    key.shadow.camera.left = -8
    key.shadow.camera.right = 8
    key.shadow.camera.top = 8
    key.shadow.camera.bottom = -8
    this.scene.add(key)
    const fill = new THREE.DirectionalLight('#9db4d8', 0.5)
    fill.position.set(-6, 3, -4)
    this.scene.add(fill)

    // Ground + grid
    const groundGeometry = new THREE.CircleGeometry(24, 48)
    const groundMaterial = new THREE.MeshStandardMaterial({ color: '#232630', roughness: 0.95 })
    const ground = new THREE.Mesh(groundGeometry, groundMaterial)
    ground.rotation.x = -Math.PI / 2
    ground.receiveShadow = true
    this.scene.add(ground)
    this.disposables.push(groundGeometry, groundMaterial)
    const grid = new THREE.GridHelper(24, 24, '#3a3f4d', '#2a2e38')
    grid.position.y = 0.001
    this.scene.add(grid)
    this.disposables.push(grid.geometry, grid.material as THREE.Material)

    // Selection ring
    const ringGeometry = new THREE.RingGeometry(0.42, 0.5, 40)
    const ringMaterial = new THREE.MeshBasicMaterial({
      color: '#8b5cf6',
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.9,
    })
    this.selectionRing = new THREE.Mesh(ringGeometry, ringMaterial)
    this.selectionRing.rotation.x = -Math.PI / 2
    this.selectionRing.visible = false
    this.scene.add(this.selectionRing)
    this.disposables.push(ringGeometry, ringMaterial)

    canvas.addEventListener('pointerdown', this.handlePointerDown)
    canvas.addEventListener('pointermove', this.handlePointerMove)
    canvas.addEventListener('pointerup', this.handlePointerUp)

    this.renderLoop()
  }

  // ---- Object lifecycle -------------------------------------------------

  private nextColor(): string {
    const used = this.entities.size
    return FIGURE_COLORS[used % FIGURE_COLORS.length]
  }

  addObject(data: CompositionObject): void {
    let node: THREE.Object3D
    let rig: FigureRig | null = null
    if (data.type === 'figure') {
      const color = data.color || this.nextColor()
      data.color = color
      rig = buildFigure(data.figure_variant, color)
      node = rig.root
      applyPose(rig, data.pose)
    } else if (data.type === 'camera') {
      return // the shot camera is managed separately, never an entity
    } else {
      const spec = PRIMITIVES[data.type] ?? PRIMITIVES.cube
      const geometry = spec.geometry()
      const material = new THREE.MeshStandardMaterial({ color: data.color || '#8a93a6', roughness: 0.8 })
      const mesh = new THREE.Mesh(geometry, material)
      mesh.castShadow = true
      mesh.position.y = spec.y
      node = new THREE.Group()
      node.add(mesh)
      this.disposables.push(geometry, material)
    }
    node.position.fromArray(data.transform.position)
    node.rotation.set(...data.transform.rotation)
    node.scale.fromArray(data.transform.scale)
    node.visible = data.visible !== false
    node.userData.entityId = data.id
    this.scene.add(node)
    this.entities.set(data.id, { data: { ...data, keyframes: [...(data.keyframes ?? [])] }, node, rig })
  }

  removeObject(id: string): void {
    const entity = this.entities.get(id)
    if (!entity) return
    if (this.gizmo.object === entity.node) this.gizmo.detach()
    this.scene.remove(entity.node)
    entity.rig?.dispose()
    this.entities.delete(id)
    if (this.selectedId === id) this.select(null)
  }

  getEntity(id: string): ComposerEntity | null {
    return this.entities.get(id) ?? null
  }

  listEntities(): ComposerEntity[] {
    return [...this.entities.values()]
  }

  /** Copy an object (transform offset by a step, pose and keyframes included). */
  duplicateObject(id: string, newId: string): CompositionObject | null {
    const entity = this.entities.get(id)
    if (!entity) return null
    const source = this.snapshotObject(entity)
    const copy: CompositionObject = {
      ...source,
      id: newId,
      name: `${source.name} copy`,
      locked: false,
      transform: {
        ...source.transform,
        position: [source.transform.position[0] + 0.8, source.transform.position[1], source.transform.position[2] + 0.4],
      },
      keyframes: source.keyframes.map(k => ({ ...k, id: newKeyframeId() })),
    }
    this.addObject(copy)
    return copy
  }

  renameObject(id: string, name: string): void {
    const entity = this.entities.get(id)
    if (entity) entity.data.name = name
  }

  setObjectLocked(id: string, locked: boolean): void {
    const entity = this.entities.get(id)
    if (!entity) return
    entity.data.locked = locked
    if (locked && this.gizmo.object === entity.node) this.gizmo.detach()
    if (!locked && this.selectedId === id) this.gizmo.attach(entity.node)
  }

  setObjectVisible(id: string, visible: boolean): void {
    const entity = this.entities.get(id)
    if (!entity) return
    entity.node.visible = visible
    entity.data.visible = visible
  }

  /** Rebuild a figure with another body variant, keeping transform, pose and keyframes. */
  setFigureVariant(id: string, variant: FigureVariant): void {
    const entity = this.entities.get(id)
    if (!entity || entity.data.type !== 'figure') return
    const wasSelected = this.selectedId === id
    const data = this.snapshotObject(entity)
    this.removeObject(id)
    this.addObject({ ...data, figure_variant: variant })
    if (wasSelected) this.select(id)
  }

  // ---- Selection / gizmo -----------------------------------------------

  select(id: string | null): void {
    this.selectedId = id
    if (id === SHOT_CAMERA_ID) {
      this.gizmo.attach(this.shotCamera)
      this.applyGizmoConstraints(null)
    } else {
      const entity = id ? this.entities.get(id) : null
      if (entity && !entity.data.locked) {
        this.gizmo.attach(entity.node)
        this.applyGizmoConstraints(entity)
      } else {
        this.gizmo.detach()
      }
    }
    this.onSelect(id)
  }

  get selected(): ComposerEntity | null {
    return this.selectedId && this.selectedId !== SHOT_CAMERA_ID
      ? (this.entities.get(this.selectedId) ?? null)
      : null
  }

  get isCameraSelected(): boolean {
    return this.selectedId === SHOT_CAMERA_ID
  }

  get gizmoMode(): GizmoMode {
    return this.gizmoModeValue
  }

  setGizmoMode(mode: GizmoMode): void {
    this.gizmoModeValue = mode
    this.gizmo.setMode(mode)
    this.applyGizmoConstraints(this.selected)
  }

  private applyGizmoConstraints(entity: ComposerEntity | null): void {
    const isFigure = entity?.data.type === 'figure'
    const mode = this.gizmoModeValue
    // Figures: slide on the floor, spin around Y, scale uniformly.
    this.gizmo.showX = true
    this.gizmo.showZ = true
    this.gizmo.showY = !(isFigure && mode === 'translate')
    if (isFigure && mode === 'rotate') {
      this.gizmo.showX = false
      this.gizmo.showZ = false
      this.gizmo.showY = true
    }
    if (this.gizmo.object === this.shotCamera && mode === 'scale') {
      this.gizmo.setMode('translate') // a camera has no scale
    }
  }

  private pointerNdc(event: PointerEvent): THREE.Vector2 {
    const rect = this.canvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
  }

  private entityAtPointer(event: PointerEvent): ComposerEntity | null {
    this.raycaster.setFromCamera(this.pointerNdc(event), this.editorCamera)
    const nodes = [...this.entities.values()].filter(e => e.node.visible).map(e => e.node)
    const hits = this.raycaster.intersectObjects(nodes, true)
    for (const hit of hits) {
      let current: THREE.Object3D | null = hit.object
      while (current) {
        const id = current.userData.entityId as string | undefined
        if (id) return this.entities.get(id) ?? null
        current = current.parent
      }
    }
    return null
  }

  private cameraAtPointer(event: PointerEvent): boolean {
    this.raycaster.setFromCamera(this.pointerNdc(event), this.editorCamera)
    const hits = this.raycaster.intersectObject(this.cameraHelper, false)
    return hits.length > 0
  }

  private handlePointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return
    // The gizmo owns the pointer while a handle is hovered/dragged.
    if (this.gizmo.axis || this.gizmo.dragging) return
    this.pointerDownAt = { x: event.clientX, y: event.clientY }
    const entity = this.entityAtPointer(event)
    if (entity) {
      this.select(entity.data.id)
      if (entity.data.locked) return
      // Begin ground-plane drag: remember grab offset so the object doesn't jump.
      this.raycaster.setFromCamera(this.pointerNdc(event), this.editorCamera)
      const hit = new THREE.Vector3()
      if (this.raycaster.ray.intersectPlane(this.groundPlane, hit)) {
        this.dragging = { id: entity.data.id, offset: entity.node.position.clone().sub(hit) }
        this.controls.enabled = false
        this.canvas.setPointerCapture(event.pointerId)
      }
    } else if (this.cameraAtPointer(event)) {
      this.select(SHOT_CAMERA_ID)
    }
  }

  private handlePointerMove = (event: PointerEvent) => {
    if (!this.dragging) return
    const entity = this.entities.get(this.dragging.id)
    if (!entity) return
    this.raycaster.setFromCamera(this.pointerNdc(event), this.editorCamera)
    const hit = new THREE.Vector3()
    if (this.raycaster.ray.intersectPlane(this.groundPlane, hit)) {
      entity.node.position.set(
        hit.x + this.dragging.offset.x,
        entity.node.position.y,
        hit.z + this.dragging.offset.z,
      )
      this.onTransformChange()
    }
  }

  private handlePointerUp = (event: PointerEvent) => {
    if (this.dragging) {
      this.dragging = null
      this.controls.enabled = true
      if (this.canvas.hasPointerCapture(event.pointerId)) {
        this.canvas.releasePointerCapture(event.pointerId)
      }
    } else if (this.pointerDownAt && !this.gizmo.dragging && !this.gizmo.axis) {
      // A true click (not an orbit drag) on empty space clears the selection.
      const moved =
        Math.abs(event.clientX - this.pointerDownAt.x) + Math.abs(event.clientY - this.pointerDownAt.y)
      if (moved < 4 && !this.entityAtPointer(event) && !this.cameraAtPointer(event)) this.select(null)
    }
    this.pointerDownAt = null
  }

  // ---- Transforms / poses ----------------------------------------------

  getObjectTransform(id: string): TransformSnapshot | null {
    const entity = this.entities.get(id)
    if (!entity) return null
    const { node } = entity
    return {
      position: [node.position.x, node.position.y, node.position.z],
      rotation: [node.rotation.x, node.rotation.y, node.rotation.z],
      scale: [node.scale.x, node.scale.y, node.scale.z],
    }
  }

  setObjectTransform(id: string, next: Partial<TransformSnapshot>): void {
    const entity = this.entities.get(id)
    if (!entity || entity.data.locked) return
    if (next.position) entity.node.position.fromArray(next.position)
    if (next.rotation) entity.node.rotation.set(...next.rotation)
    if (next.scale) entity.node.scale.fromArray(next.scale)
    this.onTransformChange()
  }

  setObjectRotationY(id: string, radians: number): void {
    const entity = this.entities.get(id)
    if (entity && !entity.data.locked) {
      entity.node.rotation.y = radians
      this.onTransformChange()
    }
  }

  setObjectPosition(id: string, position: Vec3): void {
    this.setObjectTransform(id, { position })
  }

  setJointRotation(id: string, joint: string, euler: Vec3): void {
    const entity = this.entities.get(id)
    const group = entity?.rig?.joints[joint as keyof FigureRig['joints']]
    if (group) {
      group.rotation.set(
        (euler[0] * Math.PI) / 180,
        (euler[1] * Math.PI) / 180,
        (euler[2] * Math.PI) / 180,
      )
      this.onTransformChange()
    }
  }

  applyPoseTo(id: string, pose: Record<string, Vec3>): void {
    const entity = this.entities.get(id)
    if (entity?.rig) {
      applyPose(entity.rig, pose)
      this.onTransformChange()
    }
  }

  readPoseOf(id: string): Record<string, Vec3> {
    const entity = this.entities.get(id)
    return entity?.rig ? readPose(entity.rig) : {}
  }

  // ---- Shot camera ------------------------------------------------------

  getCameraState(): { position: Vec3; rotation: Vec3; fov: number } {
    const c = this.shotCamera
    return {
      position: [c.position.x, c.position.y, c.position.z],
      rotation: [c.rotation.x, c.rotation.y, c.rotation.z],
      fov: c.fov,
    }
  }

  /** Manual camera placement (numeric inputs). Marks the camera manual. */
  setCameraState(next: { position?: Vec3; rotation?: Vec3; fov?: number }): void {
    if (next.position) this.shotCamera.position.fromArray(next.position)
    if (next.rotation) this.shotCamera.rotation.set(...next.rotation)
    if (next.fov != null) {
      this.shotCamera.fov = next.fov
      this.shotCamera.updateProjectionMatrix()
    }
    this.cameraHelper.update()
    this.onCameraManualChange()
  }

  /** Aim the shot camera at an object's chest height without moving it. */
  aimCameraAt(id: string): void {
    const entity = this.entities.get(id)
    if (!entity) return
    const anchors = getCharacterAnchors(entity.node)
    this.shotCamera.up.set(0, 1, 0)
    this.shotCamera.lookAt(new THREE.Vector3(anchors.centerX, anchors.chest, anchors.centerZ))
    this.cameraHelper.update()
    this.onCameraManualChange()
  }

  /**
   * Solve the shot camera from the framing presets against the framed subject
   * (OTS/POV use the framing's foreground character and aim at the subject
   * character). Falls back to the selected object, then the first figure.
   * In manual camera mode only the field of view is applied.
   */
  applyFraming(framing: ShotFraming): void {
    this.shotCamera.fov = framing.fov_deg
    this.shotCamera.updateProjectionMatrix()
    if (framing.camera_mode === 'manual') {
      this.cameraHelper.update()
      return
    }
    const primaryId =
      (framing.camera_angle === 'ots' || framing.camera_angle === 'pov'
        ? framing.ots_foreground_id
        : null) ??
      (this.selectedId !== SHOT_CAMERA_ID ? this.selectedId : null) ??
      this.firstFigureId()
    if (!primaryId) return
    const primary = this.entities.get(primaryId)
    if (!primary) return

    const secondaryId = framing.ots_subject_id
    const secondary =
      secondaryId && secondaryId !== primaryId ? this.entities.get(secondaryId) : null

    const solved = solveShot({
      shotSize: framing.shot_size,
      angle: framing.camera_angle,
      elevation: framing.camera_elevation,
      composition: framing.composition,
      anchors: getCharacterAnchors(primary.node),
      targetAnchors: secondary ? getCharacterAnchors(secondary.node) : undefined,
      otsShoulder: framing.ots_shoulder,
      fovDeg: framing.fov_deg,
      aspect: 16 / 9,
    })
    applySolvedShot(this.shotCamera, solved)
    this.cameraHelper.update()
    this.cameraKeyframes = []
    this.previewTime = null
  }

  firstFigureId(): string | null {
    for (const entity of this.entities.values()) {
      if (entity.data.type === 'figure') return entity.data.id
    }
    return this.entities.keys().next().value ?? null
  }

  /** Build start/end camera keyframes for a camera move from the current shot camera. */
  applyCameraMove(move: CameraMove, durationSeconds: number, intensity = 1): void {
    this.endPreview()
    const target = new THREE.Vector3()
    this.shotCamera.getWorldDirection(target)
    const focus = this.shotCamera.position.clone().addScaledVector(target, 4)
    this.cameraKeyframes = buildCameraMove(
      move,
      { position: this.shotCamera.position.clone(), target: focus, fov: this.shotCamera.fov },
      durationSeconds,
      intensity,
    )
  }

  // ---- Keyframes --------------------------------------------------------

  /** Record the shot camera's current pose as a keyframe at `time` (replaces one at the same time). */
  addCameraKeyframe(time: number): CompositionKeyframe {
    this.endPreview()
    const state = this.getCameraState()
    const keyframe: CompositionKeyframe = {
      id: newKeyframeId(),
      time,
      transform: { position: state.position, rotation: state.rotation, scale: [1, 1, 1] },
      fov: state.fov,
    }
    this.cameraKeyframes = [...this.cameraKeyframes.filter(k => Math.abs(k.time - time) > 1e-3), keyframe].sort(
      (a, b) => a.time - b.time,
    )
    this.onTransformChange()
    return keyframe
  }

  /** Record an object's current transform as a keyframe at `time`. */
  addObjectKeyframe(id: string, time: number): CompositionKeyframe | null {
    const entity = this.entities.get(id)
    if (!entity) return null
    this.endPreview()
    const transform = this.getObjectTransform(id)
    if (!transform) return null
    const keyframe: CompositionKeyframe = { id: newKeyframeId(), time, transform, fov: null }
    entity.data.keyframes = [...entity.data.keyframes.filter(k => Math.abs(k.time - time) > 1e-3), keyframe].sort(
      (a, b) => a.time - b.time,
    )
    this.onTransformChange()
    return keyframe
  }

  removeKeyframe(keyframeId: string): void {
    this.endPreview()
    this.cameraKeyframes = this.cameraKeyframes.filter(k => k.id !== keyframeId)
    for (const entity of this.entities.values()) {
      entity.data.keyframes = entity.data.keyframes.filter(k => k.id !== keyframeId)
    }
    this.onTransformChange()
  }

  setKeyframeTime(keyframeId: string, time: number): void {
    const retime = (list: CompositionKeyframe[]) =>
      list.map(k => (k.id === keyframeId ? { ...k, time: Math.max(0, time) } : k)).sort((a, b) => a.time - b.time)
    this.cameraKeyframes = retime(this.cameraKeyframes)
    for (const entity of this.entities.values()) entity.data.keyframes = retime(entity.data.keyframes)
    this.onTransformChange()
  }

  /** Jump the live camera to a camera keyframe (to tweak it and re-record). */
  goToCameraKeyframe(keyframeId: string): void {
    const keyframe = this.cameraKeyframes.find(k => k.id === keyframeId)
    if (!keyframe) return
    this.endPreview()
    this.shotCamera.position.fromArray(keyframe.transform.position)
    this.shotCamera.rotation.set(...keyframe.transform.rotation)
    if (keyframe.fov != null) {
      this.shotCamera.fov = keyframe.fov
      this.shotCamera.updateProjectionMatrix()
    }
    this.cameraHelper.update()
  }

  /** All object keyframes keyed by object id (for the timeline strip). */
  objectKeyframes(): { id: string; name: string; keyframes: CompositionKeyframe[] }[] {
    return [...this.entities.values()]
      .filter(e => e.data.keyframes.length > 0)
      .map(e => ({ id: e.data.id, name: e.data.name, keyframes: e.data.keyframes }))
  }

  /**
   * Scrub the scene along its keyframes (motion preview): camera and every
   * keyframed object. Null = back to the live, editable state.
   */
  setPreviewTime(time: number | null): void {
    if (time === null) {
      this.endPreview()
      return
    }
    if (this.liveTransforms === null) {
      this.liveTransforms = new Map()
      for (const [id] of this.entities) {
        const snapshot = this.getObjectTransform(id)
        if (snapshot) this.liveTransforms.set(id, snapshot)
      }
      this.liveCamera = this.getCameraState()
    }
    this.previewTime = time
    const sample = sampleCameraTrack(this.cameraKeyframes, time)
    if (sample) {
      this.shotCamera.position.fromArray(sample.position)
      this.shotCamera.rotation.set(...sample.rotation)
      if (sample.fov != null) {
        this.shotCamera.fov = sample.fov
        this.shotCamera.updateProjectionMatrix()
      }
      this.cameraHelper.update()
    }
    for (const entity of this.entities.values()) {
      if (entity.data.keyframes.length === 0) continue
      const objectSample = sampleCameraTrack(entity.data.keyframes, time)
      if (objectSample) {
        entity.node.position.fromArray(objectSample.position)
        entity.node.rotation.set(...objectSample.rotation)
      }
    }
  }

  get isPreviewing(): boolean {
    return this.previewTime !== null
  }

  private endPreview(): void {
    if (this.liveTransforms) {
      for (const [id, snapshot] of this.liveTransforms) {
        const entity = this.entities.get(id)
        if (!entity) continue
        entity.node.position.fromArray(snapshot.position)
        entity.node.rotation.set(...snapshot.rotation)
        entity.node.scale.fromArray(snapshot.scale)
      }
      this.liveTransforms = null
    }
    if (this.liveCamera) {
      this.shotCamera.position.fromArray(this.liveCamera.position)
      this.shotCamera.rotation.set(...this.liveCamera.rotation)
      this.shotCamera.fov = this.liveCamera.fov
      this.shotCamera.updateProjectionMatrix()
      this.cameraHelper.update()
      this.liveCamera = null
    }
    this.previewTime = null
  }

  /** Frame the editor camera on an object. */
  focusOn(id: string): void {
    const entity = this.entities.get(id)
    if (!entity) return
    const box = new THREE.Box3().setFromObject(entity.node)
    const center = box.getCenter(new THREE.Vector3())
    this.controls.target.copy(center)
  }

  // ---- Serialization ----------------------------------------------------

  private snapshotObject(entity: ComposerEntity): CompositionObject {
    const { node } = entity
    return {
      ...entity.data,
      visible: node.visible,
      transform: {
        position: [node.position.x, node.position.y, node.position.z],
        rotation: [node.rotation.x, node.rotation.y, node.rotation.z],
        scale: [node.scale.x, node.scale.y, node.scale.z],
      },
      pose: entity.rig ? readPose(entity.rig) : entity.data.pose,
      keyframes: [...entity.data.keyframes],
    }
  }

  /** Current objects as plain data (for the scene tree). */
  snapshotObjects(): CompositionObject[] {
    return [...this.entities.values()].map(e => this.snapshotObject(e))
  }

  serialize(framing: ShotFraming, cameraMove: CameraMove, durationSeconds: number): CompositionScene {
    this.endPreview()
    const objects = this.snapshotObjects()
    const state = this.getCameraState()
    const camera: CompositionObject = {
      id: SHOT_CAMERA_ID,
      name: 'Shot Camera',
      type: 'camera',
      asset_id: null,
      visible: true,
      locked: false,
      transform: { position: state.position, rotation: state.rotation, scale: [1, 1, 1] },
      pose: {},
      figure_variant: 'male',
      color: '#ffffff',
      keyframes: this.cameraKeyframes,
      fov: state.fov,
    }
    return {
      objects,
      camera,
      framing: { ...framing, fov_deg: state.fov },
      camera_move: cameraMove,
      duration_seconds: durationSeconds,
    }
  }

  /** Restore a saved composition (objects + camera + keyframes). */
  hydrate(composition: CompositionScene): void {
    for (const id of [...this.entities.keys()]) this.removeObject(id)
    for (const object of composition.objects) this.addObject(object)
    if (composition.camera) {
      this.shotCamera.position.fromArray(composition.camera.transform.position)
      this.shotCamera.rotation.set(...composition.camera.transform.rotation)
      if (composition.camera.fov != null) {
        this.shotCamera.fov = composition.camera.fov
        this.shotCamera.updateProjectionMatrix()
      }
      this.cameraKeyframes = composition.camera.keyframes ?? []
      this.cameraHelper.update()
    }
  }

  // ---- Capture ----------------------------------------------------------

  /**
   * Render the shot camera at the output aspect and return a PNG data URL.
   * The renderer is resized for the capture and restored afterwards.
   */
  capture(width = 1280, height = 720): string {
    const previousSize = new THREE.Vector2()
    this.renderer.getSize(previousSize)
    const previousPixelRatio = this.renderer.getPixelRatio()
    const helperWasVisible = this.cameraHelper.visible
    const ringWasVisible = this.selectionRing.visible
    const gizmoHelper = this.gizmo.getHelper()
    const gizmoWasVisible = gizmoHelper.visible
    this.cameraHelper.visible = false
    this.selectionRing.visible = false
    gizmoHelper.visible = false
    this.renderer.setPixelRatio(1)
    this.renderer.setSize(width, height, false)
    this.shotCamera.aspect = width / height
    this.shotCamera.updateProjectionMatrix()
    this.renderer.setViewport(0, 0, width, height)
    this.renderer.setScissorTest(false)
    this.renderer.render(this.scene, this.shotCamera)
    const dataUrl = this.canvas.toDataURL('image/png')
    this.renderer.setPixelRatio(previousPixelRatio)
    this.renderer.setSize(previousSize.x, previousSize.y, false)
    this.cameraHelper.visible = helperWasVisible
    this.selectionRing.visible = ringWasVisible
    gizmoHelper.visible = gizmoWasVisible
    return dataUrl
  }

  // ---- Render loop -------------------------------------------------------

  resize(width: number, height: number): void {
    this.renderer.setSize(width, height, false)
    this.editorCamera.aspect = width / height
    this.editorCamera.updateProjectionMatrix()
  }

  private renderLoop = () => {
    if (this.disposed) return
    this.animationFrame = requestAnimationFrame(this.renderLoop)
    this.controls.update()

    // Selection ring follows the selected object.
    const selected = this.selected
    if (selected) {
      this.selectionRing.visible = true
      this.selectionRing.position.set(
        selected.node.position.x,
        0.012,
        selected.node.position.z,
      )
    } else {
      this.selectionRing.visible = false
    }

    const size = new THREE.Vector2()
    this.renderer.getSize(size)
    const width = size.x
    const height = size.y
    if (width === 0 || height === 0) return

    const gizmoHelper = this.gizmo.getHelper()

    // Main editor view.
    this.renderer.setScissorTest(false)
    this.renderer.setViewport(0, 0, width, height)
    this.editorCamera.aspect = width / height
    this.editorCamera.updateProjectionMatrix()
    this.cameraHelper.visible = true
    gizmoHelper.visible = this.gizmo.object !== undefined && this.gizmo.object !== null
    this.renderer.render(this.scene, this.editorCamera)

    // Picture-in-picture viewfinder through the shot camera (bottom-right).
    const pipWidth = Math.round(Math.min(width * 0.32, 420))
    const pipHeight = Math.round((pipWidth * 9) / 16)
    const pad = 12
    this.cameraHelper.visible = false
    this.selectionRing.visible = false
    gizmoHelper.visible = false
    this.renderer.setScissorTest(true)
    this.renderer.setScissor(width - pipWidth - pad, pad, pipWidth, pipHeight)
    this.renderer.setViewport(width - pipWidth - pad, pad, pipWidth, pipHeight)
    this.shotCamera.aspect = 16 / 9
    this.shotCamera.updateProjectionMatrix()
    this.renderer.render(this.scene, this.shotCamera)
    this.renderer.setScissorTest(false)
  }

  dispose(): void {
    this.disposed = true
    cancelAnimationFrame(this.animationFrame)
    this.canvas.removeEventListener('pointerdown', this.handlePointerDown)
    this.canvas.removeEventListener('pointermove', this.handlePointerMove)
    this.canvas.removeEventListener('pointerup', this.handlePointerUp)
    this.gizmo.detach()
    this.gizmo.dispose()
    this.controls.dispose()
    for (const id of [...this.entities.keys()]) this.removeObject(id)
    for (const disposable of this.disposables) disposable.dispose()
    this.renderer.dispose()
  }
}
