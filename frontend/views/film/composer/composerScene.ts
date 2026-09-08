/**
 * Imperative three.js scene manager for the Shot Composer.
 *
 * Owns the renderer, editor camera (orbit), shot camera (the cinematic
 * camera), object lifecycle (figures/primitives), selection, ground-plane
 * dragging, the picture-in-picture viewfinder, capture, and motion preview.
 * React components drive it through methods and read back via callbacks;
 * during a session the three.js graph is the working state, serialized to a
 * CompositionScene on save/capture.
 *
 * Viewport interaction model (orbit editor camera + raycast select + PiP
 * viewfinder + preserveDrawingBuffer capture) adapted from Open Media's
 * ComposerViewport (MIT; see docs/INTEGRATED_UPSTREAMS.md), rebuilt in plain
 * three.js for React 18.
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type {
  CameraMove,
  CompositionKeyframe,
  CompositionObject,
  CompositionScene,
  ShotFraming,
  Vec3,
} from '../../../types/film'
import { buildCameraMove, sampleCameraTrack } from './cameraMotion'
import { applyPose, buildFigure, readPose, type FigureRig } from './figure'
import { applySolvedShot, getCharacterAnchors, solveShot } from './shotSolver'

const FIGURE_COLORS = ['#7f9cc4', '#c4907f', '#8fc47f', '#b98fc4', '#c4b97f', '#7fc4b9']

export interface ComposerEntity {
  data: CompositionObject
  node: THREE.Object3D
  rig: FigureRig | null
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

export class ComposerScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private editorCamera: THREE.PerspectiveCamera
  private controls: OrbitControls
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

  /** Camera keyframes for motion preview (start/end of the camera move). */
  cameraKeyframes: CompositionKeyframe[] = []
  private previewTime: number | null = null

  onSelect: (id: string | null) => void = () => {}
  onTransformChange: () => void = () => {}

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
      rig = buildFigure(data.figure_variant, data.color || this.nextColor())
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
    node.userData.entityId = data.id
    this.scene.add(node)
    this.entities.set(data.id, { data, node, rig })
  }

  removeObject(id: string): void {
    const entity = this.entities.get(id)
    if (!entity) return
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

  // ---- Selection / dragging --------------------------------------------

  select(id: string | null): void {
    this.selectedId = id
    this.onSelect(id)
  }

  get selected(): ComposerEntity | null {
    return this.selectedId ? (this.entities.get(this.selectedId) ?? null) : null
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
    const nodes = [...this.entities.values()].map(e => e.node)
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

  private handlePointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return
    this.pointerDownAt = { x: event.clientX, y: event.clientY }
    const entity = this.entityAtPointer(event)
    if (entity) {
      this.select(entity.data.id)
      // Begin ground-plane drag: remember grab offset so the object doesn't jump.
      this.raycaster.setFromCamera(this.pointerNdc(event), this.editorCamera)
      const hit = new THREE.Vector3()
      if (this.raycaster.ray.intersectPlane(this.groundPlane, hit)) {
        this.dragging = { id: entity.data.id, offset: entity.node.position.clone().sub(hit) }
        this.controls.enabled = false
        this.canvas.setPointerCapture(event.pointerId)
      }
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
    } else if (this.pointerDownAt) {
      // A true click (not an orbit drag) on empty space clears the selection.
      const moved =
        Math.abs(event.clientX - this.pointerDownAt.x) + Math.abs(event.clientY - this.pointerDownAt.y)
      if (moved < 4 && !this.entityAtPointer(event)) this.select(null)
    }
    this.pointerDownAt = null
  }

  // ---- Transforms / poses ----------------------------------------------

  setObjectRotationY(id: string, radians: number): void {
    const entity = this.entities.get(id)
    if (entity) {
      entity.node.rotation.y = radians
      this.onTransformChange()
    }
  }

  setObjectPosition(id: string, position: Vec3): void {
    const entity = this.entities.get(id)
    if (entity) {
      entity.node.position.fromArray(position)
      this.onTransformChange()
    }
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

  // ---- Shot solving -----------------------------------------------------

  /**
   * Solve the shot camera from the framing presets against the framed subject
   * (OTS/POV use the framing's foreground character and aim at the subject
   * character). Falls back to the selected object, then the first figure.
   */
  applyFraming(framing: ShotFraming): void {
    const primaryId =
      (framing.camera_angle === 'ots' || framing.camera_angle === 'pov'
        ? framing.ots_foreground_id
        : null) ??
      this.selectedId ??
      this.firstFigureId()
    if (!primaryId) return
    const primary = this.entities.get(primaryId)
    if (!primary) return

    const secondaryId = framing.ots_subject_id
    const secondary =
      secondaryId && secondaryId !== primaryId ? this.entities.get(secondaryId) : null

    this.shotCamera.fov = framing.fov_deg
    this.shotCamera.updateProjectionMatrix()
    const solved = solveShot({
      shotSize: framing.shot_size,
      angle: framing.camera_angle,
      elevation: framing.camera_elevation,
      composition: framing.composition,
      anchors: getCharacterAnchors(primary.node),
      targetAnchors: secondary ? getCharacterAnchors(secondary.node) : undefined,
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
  applyCameraMove(move: CameraMove, durationSeconds: number): void {
    const target = new THREE.Vector3()
    this.shotCamera.getWorldDirection(target)
    const focus = this.shotCamera.position.clone().addScaledVector(target, 4)
    this.cameraKeyframes = buildCameraMove(
      move,
      { position: this.shotCamera.position.clone(), target: focus, fov: this.shotCamera.fov },
      durationSeconds,
    )
    this.previewTime = null
  }

  /** Scrub the camera along its keyframes (motion preview). Null = live camera. */
  setPreviewTime(time: number | null): void {
    this.previewTime = time
    if (time === null) return
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

  serialize(framing: ShotFraming, cameraMove: CameraMove, durationSeconds: number): CompositionScene {
    const objects: CompositionObject[] = []
    for (const entity of this.entities.values()) {
      const { node } = entity
      objects.push({
        ...entity.data,
        transform: {
          position: [node.position.x, node.position.y, node.position.z],
          rotation: [node.rotation.x, node.rotation.y, node.rotation.z],
          scale: [node.scale.x, node.scale.y, node.scale.z],
        },
        pose: entity.rig ? readPose(entity.rig) : entity.data.pose,
      })
    }
    const camera: CompositionObject = {
      id: 'shot-camera',
      name: 'Shot Camera',
      type: 'camera',
      asset_id: null,
      visible: true,
      locked: false,
      transform: {
        position: [this.shotCamera.position.x, this.shotCamera.position.y, this.shotCamera.position.z],
        rotation: [this.shotCamera.rotation.x, this.shotCamera.rotation.y, this.shotCamera.rotation.z],
        scale: [1, 1, 1],
      },
      pose: {},
      figure_variant: 'male',
      color: '#ffffff',
      keyframes: this.cameraKeyframes,
      fov: this.shotCamera.fov,
    }
    return {
      objects,
      camera,
      framing,
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
    this.cameraHelper.visible = false
    this.selectionRing.visible = false
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

    // Main editor view.
    this.renderer.setScissorTest(false)
    this.renderer.setViewport(0, 0, width, height)
    this.editorCamera.aspect = width / height
    this.editorCamera.updateProjectionMatrix()
    this.cameraHelper.visible = true
    this.renderer.render(this.scene, this.editorCamera)

    // Picture-in-picture viewfinder through the shot camera (bottom-right).
    const pipWidth = Math.round(Math.min(width * 0.32, 420))
    const pipHeight = Math.round((pipWidth * 9) / 16)
    const pad = 12
    this.cameraHelper.visible = false
    this.selectionRing.visible = false
    this.renderer.setScissorTest(true)
    this.renderer.setScissor(width - pipWidth - pad, pad, pipWidth, pipHeight)
    this.renderer.setViewport(width - pipWidth - pad, pad, pipWidth, pipHeight)
    this.shotCamera.aspect = 16 / 9
    this.shotCamera.updateProjectionMatrix()
    this.renderer.render(this.scene, this.shotCamera)
    this.renderer.setScissorTest(false)
    void this.previewTime
  }

  dispose(): void {
    this.disposed = true
    cancelAnimationFrame(this.animationFrame)
    this.canvas.removeEventListener('pointerdown', this.handlePointerDown)
    this.canvas.removeEventListener('pointermove', this.handlePointerMove)
    this.canvas.removeEventListener('pointerup', this.handlePointerUp)
    this.controls.dispose()
    for (const id of [...this.entities.keys()]) this.removeObject(id)
    for (const disposable of this.disposables) disposable.dispose()
    this.renderer.dispose()
  }
}
