import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Aperture,
  Box,
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Columns2,
  Copy,
  Cylinder,
  Diamond,
  Eye,
  EyeOff,
  Film,
  Loader2,
  Lock,
  Maximize2,
  Move,
  PersonStanding,
  RefreshCw,
  RotateCw,
  Save,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Triangle,
  Unlock,
  Video,
  X,
} from 'lucide-react'
import { Button } from '../../../components/ui/button'
import { useFilm } from '../../../contexts/FilmContext'
import { filmApi, filmOutputUrl } from '../../../lib/film-api'
import { logger } from '../../../lib/logger'
import type {
  CameraMove,
  CompositionKeyframe,
  CompositionObject,
  CompositionObjectType,
  FigureVariant,
  FilmAsset,
  FilmScene,
  FilmShot,
  ShotFraming,
  ShotVersion,
  Vec3,
} from '../../../types/film'
import { CAMERA_ANGLES, CAMERA_ELEVATIONS, CAMERA_MOVES, COMPOSITIONS, SHOT_SIZES } from '../../../types/film'
import { useShotWorkflow } from '../useShotWorkflow'
import { ComposerScene, SHOT_CAMERA_ID, type GizmoMode } from './composerScene'
import { JOINT_LABELS, JOINT_NAMES, mirrorPose } from './figure'
import { mergePoseLibrary, type PoseEntry } from './poses'

interface ShotComposerProps {
  projectId: string
  scene: FilmScene
  shot: FilmShot
  onClose: () => void
}

let objectCounter = 0
function newObject(type: CompositionObjectType, name: string, variant: FigureVariant = 'male'): CompositionObject {
  objectCounter += 1
  return {
    id: `obj-${Date.now().toString(36)}-${objectCounter}`,
    name,
    type,
    asset_id: null,
    visible: true,
    locked: false,
    transform: { position: [objectCounter * 0.9 - 1, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    pose: {},
    figure_variant: variant,
    color: '',
    keyframes: [],
    fov: null,
  }
}

const FIGURE_VARIANTS: { id: FigureVariant; label: string }[] = [
  { id: 'male', label: 'Adult (tall)' },
  { id: 'female', label: 'Adult' },
  { id: 'child', label: 'Child' },
]

const toDeg = (rad: number) => Math.round((rad * 180) / Math.PI)
const toRad = (deg: number) => (deg * Math.PI) / 180

function PresetGrid<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string; hint?: string }[]
  value: T
  onChange: (id: T) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-1">
      {options.map(option => (
        <button
          key={option.id}
          title={option.hint}
          onClick={() => onChange(option.id)}
          className={`px-2 py-1.5 rounded text-xs text-left transition-colors ${
            value === option.id
              ? 'bg-violet-600/80 text-white'
              : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function Section({
  title,
  defaultOpen = false,
  badge,
  children,
}: {
  title: string
  defaultOpen?: boolean
  badge?: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-zinc-800">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-zinc-300 uppercase tracking-wide hover:bg-zinc-800/60"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title}
        {badge && <span className="ml-auto text-[10px] font-normal normal-case text-zinc-500">{badge}</span>}
      </button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  )
}

function NumberField({
  label,
  value,
  step = 0.1,
  min,
  max,
  onChange,
  disabled,
}: {
  label: string
  value: number
  step?: number
  min?: number
  max?: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center gap-1 text-[11px] text-zinc-400">
      <span className="w-4">{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? Number(value.toFixed(2)) : 0}
        step={step}
        min={min}
        max={max}
        disabled={disabled}
        onChange={event => onChange(Number(event.target.value))}
        className="w-16 bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[11px] text-zinc-200 tabular-nums disabled:opacity-40"
      />
    </label>
  )
}

export function ShotComposer({ projectId, scene, shot, onClose }: ShotComposerProps) {
  const { film, refresh, isGenerating } = useFilm()
  const workflow = useShotWorkflow(scene, shot)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<ComposerScene | null>(null)

  const [objects, setObjects] = useState<CompositionObject[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [framing, setFraming] = useState<ShotFraming>(shot.framing)
  const [cameraMove, setCameraMove] = useState<CameraMove>(shot.camera_move)
  const [moveIntensity, setMoveIntensity] = useState(1)
  const [previewT, setPreviewT] = useState(0)
  const [motionPreviewOn, setMotionPreviewOn] = useState(false)
  const [selectedJoint, setSelectedJoint] = useState<string>('l_arm')
  const [jointEuler, setJointEuler] = useState<Vec3>([0, 0, 0])
  const [busy, setBusy] = useState<'save' | 'capture' | 'close' | null>(null)
  const [statusNote, setStatusNote] = useState('')
  const [poseNameDraft, setPoseNameDraft] = useState('')
  const [gizmoMode, setGizmoModeState] = useState<GizmoMode>('translate')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [transformTick, setTransformTick] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [versionUrls, setVersionUrls] = useState<Record<number, string>>({})
  const [compare, setCompare] = useState<[number, number] | null>(null)
  const [genWarnings, setGenWarnings] = useState<string[]>([])
  const dirtyRef = useRef(false)

  const markDirty = useCallback(() => {
    dirtyRef.current = true
    setDirty(true)
  }, [])

  const characters = useMemo(
    () => (film?.assets ?? []).filter(a => a.kind === 'character'),
    [film],
  )
  const poseLibrary: PoseEntry[] = useMemo(
    () => mergePoseLibrary(film?.pose_library ?? []),
    [film],
  )

  const syncObjects = useCallback(() => {
    const composer = sceneRef.current
    if (composer) setObjects(composer.snapshotObjects())
  }, [])

  // ---- Scene bootstrap --------------------------------------------------

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const composer = new ComposerScene(canvas)
    sceneRef.current = composer
    composer.onSelect = id => setSelectedId(id)
    composer.onTransformChange = () => {
      markDirty()
      setTransformTick(t => t + 1)
    }
    composer.onCameraManualChange = () => {
      markDirty()
      setTransformTick(t => t + 1)
      setFraming(f => (f.camera_mode === 'manual' ? f : { ...f, camera_mode: 'manual' }))
    }

    // Hydrate from the saved composition, or seed from the shot's cast.
    if (shot.composition && shot.composition.objects.length > 0) {
      composer.hydrate(shot.composition)
      setCameraMove(shot.composition.camera_move)
      setFraming(shot.composition.framing)
    } else {
      shot.characters.forEach((shotCharacter, index) => {
        const asset = film?.assets.find(a => a.id === shotCharacter.asset_id)
        const object = newObject('figure', asset?.name ?? `Character ${index + 1}`)
        object.asset_id = shotCharacter.asset_id
        object.transform.position = [index * 1.2 - (shot.characters.length - 1) * 0.6, 0, 0]
        composer.addObject(object)
      })
      if (shot.characters.length === 0) composer.addObject(newObject('figure', 'Character 1'))
      composer.applyFraming(shot.framing)
    }
    setObjects(composer.snapshotObjects())
    dirtyRef.current = false
    setDirty(false)

    const resize = () => {
      const rect = container.getBoundingClientRect()
      composer.resize(rect.width, rect.height)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(container)
    return () => {
      observer.disconnect()
      composer.dispose()
      sceneRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shot.id])

  // Re-solve the camera whenever framing presets change (manual mode keeps the camera).
  useEffect(() => {
    sceneRef.current?.applyFraming(framing)
  }, [framing])

  // Sync joint sliders when the selection or joint changes.
  useEffect(() => {
    if (!selectedId || selectedId === SHOT_CAMERA_ID) return
    const pose = sceneRef.current?.readPoseOf(selectedId) ?? {}
    setJointEuler(pose[selectedJoint] ?? [0, 0, 0])
  }, [selectedId, selectedJoint])

  // Motion preview scrubber drives the camera + keyframed objects.
  useEffect(() => {
    const composer = sceneRef.current
    if (!composer) return
    const hasTrack = composer.cameraKeyframes.length > 1 || composer.objectKeyframes().length > 0
    if (motionPreviewOn && hasTrack) {
      composer.setPreviewTime(previewT * shot.duration_seconds)
    } else {
      composer.setPreviewTime(null)
    }
  }, [motionPreviewOn, previewT, shot.duration_seconds, transformTick])

  // Keyboard: W/E/R gizmo modes, Delete removes, Escape deselects.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')) return
      const composer = sceneRef.current
      if (!composer) return
      if (event.key === 'w' || event.key === 'W') setGizmoMode('translate')
      else if (event.key === 'e' || event.key === 'E') setGizmoMode('rotate')
      else if (event.key === 'r' || event.key === 'R') setGizmoMode('scale')
      else if (event.key === 'Escape') composer.select(null)
      else if ((event.key === 'Delete' || event.key === 'Backspace') && selectedId && selectedId !== SHOT_CAMERA_ID) {
        removeObject(selectedId)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // Playable URLs for completed versions.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const next: Record<number, string> = {}
      for (const version of shot.versions) {
        if (version.status === 'complete' && version.output_path) {
          next[version.number] = await filmOutputUrl(version.output_path)
        }
      }
      if (!cancelled) setVersionUrls(next)
    })()
    return () => {
      cancelled = true
    }
  }, [shot.versions])

  const setGizmoMode = useCallback((mode: GizmoMode) => {
    sceneRef.current?.setGizmoMode(mode)
    setGizmoModeState(mode)
  }, [])

  // ---- Object actions ---------------------------------------------------

  const addFigure = useCallback(
    (variant: FigureVariant, asset?: FilmAsset) => {
      const composer = sceneRef.current
      if (!composer) return
      const object = newObject('figure', asset?.name ?? `Character ${objects.length + 1}`, variant)
      if (asset) object.asset_id = asset.id
      composer.addObject(object)
      syncObjects()
      composer.select(object.id)
      markDirty()
    },
    [objects.length, syncObjects, markDirty],
  )

  const addPrimitive = useCallback(
    (type: CompositionObjectType, label: string) => {
      const composer = sceneRef.current
      if (!composer) return
      const object = newObject(type, label)
      composer.addObject(object)
      syncObjects()
      composer.select(object.id)
      markDirty()
    },
    [syncObjects, markDirty],
  )

  const removeObject = useCallback(
    (id: string) => {
      const composer = sceneRef.current
      if (!composer) return
      if (composer.getEntity(id)?.data.locked) {
        setStatusNote('Unlock the object before deleting it')
        return
      }
      composer.removeObject(id)
      syncObjects()
      markDirty()
    },
    [syncObjects, markDirty],
  )

  const duplicateObject = useCallback(
    (id: string) => {
      const composer = sceneRef.current
      if (!composer) return
      objectCounter += 1
      const copy = composer.duplicateObject(id, `obj-${Date.now().toString(36)}-${objectCounter}`)
      if (copy) {
        syncObjects()
        composer.select(copy.id)
        markDirty()
      }
    },
    [syncObjects, markDirty],
  )

  const toggleVisible = useCallback(
    (id: string) => {
      const composer = sceneRef.current
      const entity = composer?.getEntity(id)
      if (!composer || !entity) return
      composer.setObjectVisible(id, !entity.node.visible)
      syncObjects()
      markDirty()
    },
    [syncObjects, markDirty],
  )

  const toggleLocked = useCallback(
    (id: string) => {
      const composer = sceneRef.current
      const entity = composer?.getEntity(id)
      if (!composer || !entity) return
      composer.setObjectLocked(id, !entity.data.locked)
      syncObjects()
      markDirty()
    },
    [syncObjects, markDirty],
  )

  const commitRename = useCallback(() => {
    const composer = sceneRef.current
    if (!composer || !renamingId) return
    const name = renameDraft.trim()
    if (name) {
      composer.renameObject(renamingId, name)
      syncObjects()
      markDirty()
    }
    setRenamingId(null)
  }, [renamingId, renameDraft, syncObjects, markDirty])

  const setVariant = useCallback(
    (id: string, variant: FigureVariant) => {
      sceneRef.current?.setFigureVariant(id, variant)
      syncObjects()
      markDirty()
    },
    [syncObjects, markDirty],
  )

  const applyPoseEntry = useCallback(
    (entry: PoseEntry) => {
      if (!selectedId) return
      sceneRef.current?.applyPoseTo(selectedId, entry.joints)
      setJointEuler(entry.joints[selectedJoint] ?? [0, 0, 0])
    },
    [selectedId, selectedJoint],
  )

  const updateJoint = useCallback(
    (axis: 0 | 1 | 2, value: number) => {
      if (!selectedId) return
      const next: Vec3 = [...jointEuler]
      next[axis] = value
      setJointEuler(next)
      sceneRef.current?.setJointRotation(selectedId, selectedJoint, next)
    },
    [jointEuler, selectedId, selectedJoint],
  )

  const savePoseToLibrary = useCallback(async () => {
    if (!selectedId || !poseNameDraft.trim()) return
    const joints = sceneRef.current?.readPoseOf(selectedId) ?? {}
    try {
      await filmApi.savePose(projectId, poseNameDraft.trim(), joints)
      setPoseNameDraft('')
      await refresh()
      setStatusNote('Pose saved to the project library')
    } catch (e) {
      setStatusNote(`Pose save failed: ${e instanceof Error ? e.message : e}`)
    }
  }, [selectedId, poseNameDraft, projectId, refresh])

  // ---- Derived selection state -----------------------------------------

  const selectedObject = selectedId && selectedId !== SHOT_CAMERA_ID ? (objects.find(o => o.id === selectedId) ?? null) : null
  const cameraSelected = selectedId === SHOT_CAMERA_ID
  const selectedTransform = useMemo(
    () => (selectedObject ? sceneRef.current?.getObjectTransform(selectedObject.id) ?? null : null),
    // transformTick forces a re-read after gizmo/drag edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedObject, transformTick],
  )
  const cameraState = useMemo(
    () => sceneRef.current?.getCameraState() ?? { position: [0, 1.6, 4] as Vec3, rotation: [0, 0, 0] as Vec3, fov: framing.fov_deg },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transformTick, framing],
  )
  const needsOts = framing.camera_angle === 'ots' || framing.camera_angle === 'pov'
  const figureObjects = objects.filter(o => o.type === 'figure')
  const cameraKeyframes = sceneRef.current?.cameraKeyframes ?? []
  const objectTracks = sceneRef.current?.objectKeyframes() ?? []
  void transformTick

  const updateSelectedTransform = useCallback(
    (patch: { x?: number; y?: number; z?: number; yawDeg?: number; scale?: number }) => {
      const composer = sceneRef.current
      if (!composer || !selectedObject) return
      const current = composer.getObjectTransform(selectedObject.id)
      if (!current) return
      composer.setObjectTransform(selectedObject.id, {
        position: [patch.x ?? current.position[0], patch.y ?? current.position[1], patch.z ?? current.position[2]],
        rotation: patch.yawDeg != null ? [current.rotation[0], toRad(patch.yawDeg), current.rotation[2]] : undefined,
        scale: patch.scale != null ? [patch.scale, patch.scale, patch.scale] : undefined,
      })
    },
    [selectedObject],
  )

  const updateCamera = useCallback((patch: { x?: number; y?: number; z?: number; fov?: number }) => {
    const composer = sceneRef.current
    if (!composer) return
    const current = composer.getCameraState()
    composer.setCameraState({
      position: [patch.x ?? current.position[0], patch.y ?? current.position[1], patch.z ?? current.position[2]],
      fov: patch.fov,
    })
    if (patch.fov != null) setFraming(f => ({ ...f, fov_deg: patch.fov ?? f.fov_deg, camera_mode: 'manual' }))
  }, [])

  // ---- Save / capture ---------------------------------------------------

  const serialize = useCallback(() => {
    const composer = sceneRef.current
    if (!composer) return null
    if (cameraMove !== 'static' && composer.cameraKeyframes.length < 2) {
      composer.applyCameraMove(cameraMove, shot.duration_seconds, moveIntensity)
    }
    return composer.serialize(framing, cameraMove, shot.duration_seconds)
  }, [framing, cameraMove, moveIntensity, shot.duration_seconds])

  const saveComposition = useCallback(async (): Promise<boolean> => {
    const composition = serialize()
    if (!composition) return false
    setBusy('save')
    try {
      await filmApi.updateShot(projectId, scene.id, shot.id, { composition })
      await refresh()
      dirtyRef.current = false
      setDirty(false)
      setStatusNote('Composition saved')
      return true
    } catch (e) {
      logger.error(`Save composition failed: ${e}`)
      setStatusNote(`Save failed: ${e instanceof Error ? e.message : e}`)
      return false
    } finally {
      setBusy(null)
    }
  }, [serialize, projectId, scene.id, shot.id, refresh])

  const captureShot = useCallback(async (): Promise<boolean> => {
    const composer = sceneRef.current
    const composition = serialize()
    if (!composer || !composition) return false
    setBusy('capture')
    try {
      composer.setPreviewTime(null)
      const dataUrl = composer.capture(1280, 720)
      await filmApi.captureShot(projectId, scene.id, shot.id, dataUrl, composition)
      await refresh()
      dirtyRef.current = false
      setDirty(false)
      setStatusNote('Shot captured — reference image saved')
      return true
    } catch (e) {
      logger.error(`Capture failed: ${e}`)
      setStatusNote(`Capture failed: ${e instanceof Error ? e.message : e}`)
      return false
    } finally {
      setBusy(null)
    }
  }, [serialize, projectId, scene.id, shot.id, refresh])

  const closeComposer = useCallback(async () => {
    if (dirtyRef.current && busy === null) {
      setBusy('close')
      const saved = await saveComposition()
      setBusy(null)
      if (!saved) {
        const discard = window.confirm('Saving failed. Close and discard the unsaved composition?')
        if (!discard) return
      }
    }
    onClose()
  }, [busy, saveComposition, onClose])

  /** Capture (fresh reference) then queue a preview/final render from inside the composer. */
  const generateFromComposer = useCallback(
    async (kind: 'preview' | 'final') => {
      setGenWarnings([])
      const captured = await captureShot()
      if (!captured) return
      const warnings = await workflow.generate(kind)
      if (warnings) setGenWarnings(warnings.map(w => w.message))
    },
    [captureShot, workflow],
  )

  const objectIcon = (type: CompositionObjectType) => {
    switch (type) {
      case 'figure':
        return <PersonStanding className="h-3.5 w-3.5" />
      case 'sphere':
        return <Circle className="h-3.5 w-3.5" />
      case 'cylinder':
        return <Cylinder className="h-3.5 w-3.5" />
      case 'cone':
        return <Triangle className="h-3.5 w-3.5" />
      default:
        return <Box className="h-3.5 w-3.5" />
    }
  }

  const completeVersions = shot.versions.filter(v => v.status === 'complete')
  const currentVersion: ShotVersion | undefined = workflow.currentVersion
  const queueInfo = workflow.queueInfo
  const anyBusy = busy !== null || workflow.busy !== null
  const previewSeconds = previewT * shot.duration_seconds

  return (
    <div className="fixed inset-0 z-[55] bg-zinc-950 flex flex-col" role="dialog" aria-label="Shot Composer">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-800 bg-zinc-900/80">
        <Aperture className="h-4 w-4 text-violet-400" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white truncate">
            Shot Composer — {scene.title} · {shot.title || `Shot ${shot.order + 1}`}
            {dirty && <span className="ml-2 text-[10px] font-normal text-amber-300">unsaved</span>}
          </div>
          <div className="text-[11px] text-zinc-500">
            Click to select · drag on the floor or use the gizmo (W move · E rotate · R scale) · click the camera frustum to move the shot camera
          </div>
        </div>
        <div className="flex items-center rounded-lg border border-zinc-700 overflow-hidden" role="group" aria-label="Gizmo mode">
          {(
            [
              ['translate', Move, 'Move (W)'],
              ['rotate', RotateCw, 'Rotate (E)'],
              ['scale', Maximize2, 'Scale (R)'],
            ] as const
          ).map(([mode, Icon, title]) => (
            <button
              key={mode}
              title={title}
              aria-pressed={gizmoMode === mode}
              onClick={() => setGizmoMode(mode)}
              className={`p-1.5 ${gizmoMode === mode ? 'bg-violet-600/70 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}
            >
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>
        {(statusNote || workflow.note) && (
          <span className="text-xs text-zinc-400 truncate max-w-[16rem]" role="status">
            {statusNote || workflow.note}
          </span>
        )}
        <Button size="sm" variant="secondary" onClick={() => void saveComposition()} disabled={anyBusy} className="gap-1.5">
          {busy === 'save' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save
        </Button>
        <Button size="sm" onClick={() => void captureShot()} disabled={anyBusy} className="gap-1.5">
          {busy === 'capture' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Camera className="h-3.5 w-3.5" />}
          Capture Shot
        </Button>
        <button
          onClick={() => void closeComposer()}
          aria-label="Close composer"
          title={dirty ? 'Saves the composition, then closes' : 'Close'}
          className="p-2 rounded hover:bg-zinc-800 text-zinc-400"
        >
          {busy === 'close' ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
        </button>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* Left: scene tree */}
        <aside className="w-60 border-r border-zinc-800 bg-zinc-900/60 flex flex-col">
          <div className="px-3 py-2 text-xs font-semibold text-zinc-400 uppercase tracking-wide">Scene</div>
          <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
            <div
              className={`flex items-center gap-1.5 px-2 py-1.5 rounded text-xs cursor-pointer ${
                cameraSelected ? 'bg-violet-600/30 text-white' : 'text-zinc-300 hover:bg-zinc-800'
              }`}
              onClick={() => sceneRef.current?.select(SHOT_CAMERA_ID)}
            >
              <Video className="h-3.5 w-3.5" />
              <span className="flex-1 truncate">Shot Camera</span>
              <span className="text-[10px] text-zinc-500">{framing.camera_mode === 'manual' ? 'manual' : 'preset'}</span>
            </div>
            {objects.map(object => (
              <div
                key={object.id}
                className={`group flex items-center gap-1.5 px-2 py-1.5 rounded text-xs cursor-pointer ${
                  selectedId === object.id ? 'bg-violet-600/30 text-white' : 'text-zinc-300 hover:bg-zinc-800'
                } ${object.visible ? '' : 'opacity-50'}`}
                onClick={() => sceneRef.current?.select(object.id)}
                onDoubleClick={() => {
                  setRenamingId(object.id)
                  setRenameDraft(object.name)
                }}
              >
                {objectIcon(object.type)}
                {renamingId === object.id ? (
                  <input
                    autoFocus
                    value={renameDraft}
                    onChange={event => setRenameDraft(event.target.value)}
                    onBlur={commitRename}
                    onKeyDown={event => {
                      if (event.key === 'Enter') commitRename()
                      if (event.key === 'Escape') setRenamingId(null)
                    }}
                    onClick={event => event.stopPropagation()}
                    className="flex-1 min-w-0 bg-zinc-800 border border-violet-600 rounded px-1 py-0 text-xs text-white"
                    aria-label="Object name"
                  />
                ) : (
                  <span className="flex-1 truncate" title="Double-click to rename">
                    {object.name}
                  </span>
                )}
                <button
                  onClick={event => {
                    event.stopPropagation()
                    toggleLocked(object.id)
                  }}
                  title={object.locked ? 'Unlock' : 'Lock'}
                  aria-label={object.locked ? `Unlock ${object.name}` : `Lock ${object.name}`}
                  className={`${object.locked ? 'text-amber-300' : 'text-zinc-600 opacity-0 group-hover:opacity-100'} hover:text-zinc-300`}
                >
                  {object.locked ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
                </button>
                <button
                  onClick={event => {
                    event.stopPropagation()
                    toggleVisible(object.id)
                  }}
                  aria-label={object.visible ? `Hide ${object.name}` : `Show ${object.name}`}
                  className="text-zinc-500 hover:text-zinc-300"
                >
                  {object.visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                </button>
              </div>
            ))}
          </div>
          <div className="border-t border-zinc-800 p-2 space-y-1.5">
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide px-1">Add character</div>
            <div className="flex flex-wrap gap-1">
              {characters.length > 0 ? (
                characters.map(asset => (
                  <button
                    key={asset.id}
                    onClick={() => addFigure('male', asset)}
                    className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-200"
                  >
                    {asset.name}
                  </button>
                ))
              ) : (
                <span className="text-[11px] text-zinc-600 px-1">No characters yet</span>
              )}
              <button
                onClick={() => addFigure('male')}
                className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-400"
              >
                + Figure
              </button>
            </div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-wide px-1 pt-1">Add prop shape</div>
            <div className="flex flex-wrap gap-1">
              {(['cube', 'cylinder', 'sphere', 'cone', 'plane'] as const).map(type => (
                <button
                  key={type}
                  onClick={() => addPrimitive(type, type[0].toUpperCase() + type.slice(1))}
                  className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300 capitalize"
                >
                  {type}
                </button>
              ))}
            </div>
            {selectedObject && (
              <div className="flex gap-1 pt-1">
                <button
                  onClick={() => duplicateObject(selectedObject.id)}
                  className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300"
                >
                  <Copy className="h-3 w-3" /> Duplicate
                </button>
                <button
                  onClick={() => removeObject(selectedObject.id)}
                  disabled={selectedObject.locked}
                  className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded bg-red-950/60 hover:bg-red-900/60 disabled:opacity-40 text-[11px] text-red-300"
                >
                  <Trash2 className="h-3 w-3" /> Delete
                </button>
              </div>
            )}
          </div>
        </aside>

        {/* Center: viewport */}
        <div ref={containerRef} className="flex-1 relative min-w-0">
          <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
          {selectedObject && selectedTransform && (
            <div className="absolute top-3 left-3 bg-zinc-900/85 rounded-lg px-2.5 py-2 border border-zinc-700 space-y-1.5">
              <div className="flex items-center gap-2 text-[11px] text-zinc-300">
                {objectIcon(selectedObject.type)}
                <span className="font-medium">{selectedObject.name}</span>
                {selectedObject.locked && <span className="text-amber-300 text-[10px]">locked</span>}
                {selectedObject.type === 'figure' && (
                  <select
                    value={selectedObject.figure_variant}
                    onChange={event => setVariant(selectedObject.id, event.target.value as FigureVariant)}
                    className="ml-auto bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[10px] text-zinc-200"
                    aria-label="Body type"
                  >
                    {FIGURE_VARIANTS.map(v => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="flex items-center gap-2">
                <NumberField label="X" value={selectedTransform.position[0]} onChange={x => updateSelectedTransform({ x })} disabled={selectedObject.locked} />
                {selectedObject.type !== 'figure' && (
                  <NumberField label="Y" value={selectedTransform.position[1]} onChange={y => updateSelectedTransform({ y })} disabled={selectedObject.locked} />
                )}
                <NumberField label="Z" value={selectedTransform.position[2]} onChange={z => updateSelectedTransform({ z })} disabled={selectedObject.locked} />
              </div>
              <div className="flex items-center gap-2">
                <NumberField label="Yaw" value={toDeg(selectedTransform.rotation[1])} step={5} onChange={yawDeg => updateSelectedTransform({ yawDeg })} disabled={selectedObject.locked} />
                <NumberField label="Sc" value={selectedTransform.scale[1]} step={0.05} min={0.05} max={20} onChange={scale => updateSelectedTransform({ scale })} disabled={selectedObject.locked} />
                <div className="flex items-center gap-0.5">
                  {[-45, -15, 15, 45].map(deg => (
                    <button
                      key={deg}
                      disabled={selectedObject.locked}
                      onClick={() => updateSelectedTransform({ yawDeg: toDeg(selectedTransform.rotation[1]) + deg })}
                      className="px-1 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[10px] text-zinc-200"
                    >
                      {deg > 0 ? `+${deg}` : deg}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
          {cameraSelected && (
            <div className="absolute top-3 left-3 bg-zinc-900/85 rounded-lg px-2.5 py-2 border border-zinc-700 space-y-1.5">
              <div className="flex items-center gap-2 text-[11px] text-zinc-300">
                <Video className="h-3.5 w-3.5" />
                <span className="font-medium">Shot Camera</span>
                <span className={`text-[10px] ${framing.camera_mode === 'manual' ? 'text-amber-300' : 'text-zinc-500'}`}>
                  {framing.camera_mode === 'manual' ? 'manual' : 'from presets'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <NumberField label="X" value={cameraState.position[0]} onChange={x => updateCamera({ x })} />
                <NumberField label="Y" value={cameraState.position[1]} onChange={y => updateCamera({ y })} />
                <NumberField label="Z" value={cameraState.position[2]} onChange={z => updateCamera({ z })} />
              </div>
              <div className="flex items-center gap-2">
                <NumberField label="FOV" value={cameraState.fov} step={1} min={10} max={120} onChange={fov => updateCamera({ fov })} />
                <select
                  defaultValue=""
                  onChange={event => {
                    if (event.target.value) sceneRef.current?.aimCameraAt(event.target.value)
                    event.target.value = ''
                  }}
                  className="bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[10px] text-zinc-200"
                  aria-label="Aim camera at"
                >
                  <option value="">Aim at…</option>
                  {objects.map(o => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
                {framing.camera_mode === 'manual' && (
                  <button
                    onClick={() => setFraming(f => ({ ...f, camera_mode: 'preset' }))}
                    className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-violet-300"
                    title="Discard the manual placement and re-solve the camera from the shot presets"
                  >
                    Back to presets
                  </button>
                )}
              </div>
            </div>
          )}
          {queueInfo.active && (
            <div className="absolute bottom-3 left-3 flex items-center gap-2 bg-zinc-900/90 rounded-lg px-3 py-2 border border-violet-800 text-[11px] text-violet-200">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Rendering this shot{queueInfo.progress != null ? ` · ${Math.round(queueInfo.progress)}%` : ''}
              {queueInfo.phase ? ` · ${queueInfo.phase}` : ''}
            </div>
          )}
        </div>

        {/* Right: inspector panels */}
        <aside className="w-80 border-l border-zinc-800 bg-zinc-900/60 overflow-y-auto">
          <Section title="Shot" defaultOpen>
            <div className="space-y-2.5">
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Shot size</div>
                <PresetGrid options={SHOT_SIZES} value={framing.shot_size} onChange={id => setFraming(f => ({ ...f, shot_size: id, camera_mode: 'preset' }))} />
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Angle</div>
                <PresetGrid options={CAMERA_ANGLES} value={framing.camera_angle} onChange={id => setFraming(f => ({ ...f, camera_angle: id, camera_mode: 'preset' }))} />
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Elevation</div>
                <PresetGrid options={CAMERA_ELEVATIONS} value={framing.camera_elevation} onChange={id => setFraming(f => ({ ...f, camera_elevation: id, camera_mode: 'preset' }))} />
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Composition</div>
                <PresetGrid options={COMPOSITIONS} value={framing.composition} onChange={id => setFraming(f => ({ ...f, composition: id, camera_mode: 'preset' }))} />
              </div>
              {framing.camera_mode === 'manual' && (
                <p className="text-[10px] text-amber-300/90">
                  Camera is placed manually — presets only change the field of view until you choose “Back to presets”.
                </p>
              )}
              {needsOts && (
                <div className="space-y-1.5 border border-zinc-800 rounded p-2">
                  <div className="text-[10px] text-violet-300 uppercase tracking-wide">Over-the-shoulder relationship</div>
                  <label className="block text-[11px] text-zinc-400">
                    Foreground (camera behind)
                    <select
                      value={framing.ots_foreground_id ?? ''}
                      onChange={event => setFraming(f => ({ ...f, ots_foreground_id: event.target.value || null, camera_mode: 'preset' }))}
                      className="mt-0.5 w-full bg-zinc-800 border border-zinc-700 rounded px-1.5 py-1 text-xs text-zinc-200"
                    >
                      <option value="">Selected / first figure</option>
                      {figureObjects.map(o => (
                        <option key={o.id} value={o.id}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-[11px] text-zinc-400">
                    Subject (looking toward)
                    <select
                      value={framing.ots_subject_id ?? ''}
                      onChange={event => setFraming(f => ({ ...f, ots_subject_id: event.target.value || null, camera_mode: 'preset' }))}
                      className="mt-0.5 w-full bg-zinc-800 border border-zinc-700 rounded px-1.5 py-1 text-xs text-zinc-200"
                    >
                      <option value="">Ahead of foreground</option>
                      {figureObjects.map(o => (
                        <option key={o.id} value={o.id}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {framing.camera_angle === 'ots' && (
                    <div className="flex items-center gap-1 text-[11px] text-zinc-400">
                      <span className="flex-1">Over the</span>
                      {(['left', 'right'] as const).map(side => (
                        <button
                          key={side}
                          onClick={() => setFraming(f => ({ ...f, ots_shoulder: side, camera_mode: 'preset' }))}
                          aria-pressed={framing.ots_shoulder === side}
                          className={`px-2 py-0.5 rounded text-[11px] capitalize ${
                            framing.ots_shoulder === side ? 'bg-violet-600/80 text-white' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                          }`}
                        >
                          {side} shoulder
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </Section>

          <Section title="Camera" badge={framing.camera_mode === 'manual' ? 'manual' : 'preset'}>
            <label className="block text-[11px] text-zinc-400">
              Field of view — {framing.fov_deg.toFixed(0)}° (≈{Math.round(1039 / framing.fov_deg)}mm)
              <input
                type="range"
                min={15}
                max={90}
                step={1}
                value={framing.fov_deg}
                onChange={event => setFraming(f => ({ ...f, fov_deg: Number(event.target.value) }))}
                className="w-full mt-1"
              />
            </label>
            <div className="flex gap-1 mt-2">
              <button
                onClick={() => sceneRef.current?.select(SHOT_CAMERA_ID)}
                className="flex-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300"
              >
                Select camera (gizmo)
              </button>
              <button
                onClick={() => setFraming(f => ({ ...f, camera_mode: f.camera_mode === 'manual' ? 'preset' : 'manual' }))}
                className="flex-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300"
              >
                {framing.camera_mode === 'manual' ? 'Re-solve from presets' : 'Keep camera manual'}
              </button>
            </div>
            <p className="text-[10px] text-zinc-600 mt-1">
              Presets re-solve the camera; moving it by hand switches to manual and the presets stop overriding it.
            </p>
          </Section>

          <Section title="Pose">
            {selectedObject && sceneRef.current?.getEntity(selectedObject.id)?.rig ? (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-1">
                  {poseLibrary.map(entry => (
                    <button
                      key={entry.id}
                      onClick={() => applyPoseEntry(entry)}
                      title={entry.source === 'project' ? 'Project pose' : 'Built-in pose'}
                      className={`px-2 py-1 rounded text-[11px] ${
                        entry.source === 'project'
                          ? 'bg-violet-900/50 text-violet-200 hover:bg-violet-800/50'
                          : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                      }`}
                    >
                      {entry.name}
                    </button>
                  ))}
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => selectedId && sceneRef.current?.applyPoseTo(selectedId, {})}
                    className="flex-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300"
                  >
                    Reset pose
                  </button>
                  <button
                    onClick={() => {
                      if (!selectedId) return
                      const composer = sceneRef.current
                      if (!composer) return
                      composer.applyPoseTo(selectedId, mirrorPose(composer.readPoseOf(selectedId)))
                    }}
                    className="flex-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300"
                  >
                    Mirror
                  </button>
                </div>
                <div className="border-t border-zinc-800 pt-2 space-y-1">
                  <select
                    value={selectedJoint}
                    onChange={event => setSelectedJoint(event.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded px-1.5 py-1 text-xs text-zinc-200"
                    aria-label="Joint"
                  >
                    {JOINT_NAMES.map(name => (
                      <option key={name} value={name}>
                        {JOINT_LABELS[name]}
                      </option>
                    ))}
                  </select>
                  {(['X', 'Y', 'Z'] as const).map((axis, index) => (
                    <label key={axis} className="flex items-center gap-2 text-[11px] text-zinc-400">
                      <span className="w-3">{axis}</span>
                      <input
                        type="range"
                        min={-160}
                        max={160}
                        step={1}
                        value={jointEuler[index as 0 | 1 | 2]}
                        onChange={event => updateJoint(index as 0 | 1 | 2, Number(event.target.value))}
                        className="flex-1"
                      />
                      <span className="w-8 text-right tabular-nums">{jointEuler[index as 0 | 1 | 2].toFixed(0)}°</span>
                    </label>
                  ))}
                </div>
                <div className="flex gap-1 pt-1">
                  <input
                    value={poseNameDraft}
                    onChange={event => setPoseNameDraft(event.target.value)}
                    placeholder="Save pose as…"
                    className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600"
                  />
                  <button
                    onClick={() => void savePoseToLibrary()}
                    disabled={!poseNameDraft.trim()}
                    className="px-2 py-1 rounded bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-[11px] text-white"
                    aria-label="Save pose"
                  >
                    <Check className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-zinc-600">Select a character figure to pose it.</p>
            )}
          </Section>

          <Section title="Motion" badge={cameraMove !== 'static' ? cameraMove.replace('_', ' ') : undefined}>
            <div className="space-y-2">
              <PresetGrid
                options={CAMERA_MOVES}
                value={cameraMove}
                onChange={id => {
                  setCameraMove(id)
                  sceneRef.current?.applyCameraMove(id, shot.duration_seconds, moveIntensity)
                  setMotionPreviewOn(id !== 'static')
                  setPreviewT(0)
                  markDirty()
                  setTransformTick(t => t + 1)
                }}
              />
              {cameraMove !== 'static' && (
                <label className="block text-[11px] text-zinc-400">
                  Intensity — {moveIntensity.toFixed(1)}×
                  <input
                    type="range"
                    min={0.3}
                    max={2.5}
                    step={0.1}
                    value={moveIntensity}
                    onChange={event => {
                      const next = Number(event.target.value)
                      setMoveIntensity(next)
                      sceneRef.current?.applyCameraMove(cameraMove, shot.duration_seconds, next)
                      markDirty()
                      setTransformTick(t => t + 1)
                    }}
                    className="w-full mt-1"
                  />
                </label>
              )}
              <div className="border-t border-zinc-800 pt-2 space-y-1">
                <div className="flex items-center gap-2 text-[10px] text-zinc-500 uppercase tracking-wide">
                  Timeline
                  <span className="ml-auto normal-case text-zinc-600">{shot.duration_seconds.toFixed(1)}s shot</span>
                </div>
                <label className="flex items-center gap-2 text-[11px] text-zinc-400">
                  <input type="checkbox" checked={motionPreviewOn} onChange={event => setMotionPreviewOn(event.target.checked)} />
                  Preview motion
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={previewT}
                  onChange={event => setPreviewT(Number(event.target.value))}
                  className="w-full"
                  aria-label="Scrub time"
                />
                <div className="text-[10px] text-zinc-600 flex items-center">
                  <span>0s</span>
                  <span className="flex-1 text-center text-zinc-400">{previewSeconds.toFixed(2)}s</span>
                  <span>{shot.duration_seconds.toFixed(1)}s</span>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => {
                      sceneRef.current?.addCameraKeyframe(previewSeconds)
                      setTransformTick(t => t + 1)
                    }}
                    className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-300"
                    title="Record the shot camera's current pose at the scrub time"
                  >
                    <Diamond className="h-3 w-3" /> Key camera
                  </button>
                  <button
                    disabled={!selectedObject}
                    onClick={() => {
                      if (selectedObject) sceneRef.current?.addObjectKeyframe(selectedObject.id, previewSeconds)
                      setTransformTick(t => t + 1)
                    }}
                    className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[11px] text-zinc-300"
                    title="Record the selected object's position/rotation at the scrub time"
                  >
                    <Diamond className="h-3 w-3" /> Key {selectedObject ? selectedObject.name : 'object'}
                  </button>
                </div>
                <KeyframeList
                  title="Camera"
                  keyframes={cameraKeyframes}
                  duration={shot.duration_seconds}
                  onGoTo={id => {
                    sceneRef.current?.goToCameraKeyframe(id)
                    setMotionPreviewOn(false)
                    setTransformTick(t => t + 1)
                  }}
                  onDelete={id => {
                    sceneRef.current?.removeKeyframe(id)
                    setTransformTick(t => t + 1)
                  }}
                  onRetime={(id, time) => {
                    sceneRef.current?.setKeyframeTime(id, time)
                    setTransformTick(t => t + 1)
                  }}
                />
                {objectTracks.map(track => (
                  <KeyframeList
                    key={track.id}
                    title={track.name}
                    keyframes={track.keyframes}
                    duration={shot.duration_seconds}
                    onDelete={id => {
                      sceneRef.current?.removeKeyframe(id)
                      setTransformTick(t => t + 1)
                    }}
                    onRetime={(id, time) => {
                      sceneRef.current?.setKeyframeTime(id, time)
                      setTransformTick(t => t + 1)
                    }}
                  />
                ))}
                <p className="text-[10px] text-zinc-600">
                  Keyframes drive the composer preview and the capture; the video model receives the camera move as prompt language.
                </p>
              </div>
            </div>
          </Section>

          <Section title="Generate" defaultOpen badge={shot.versions.length ? `${shot.versions.length} version${shot.versions.length === 1 ? '' : 's'}` : undefined}>
            <div className="space-y-2">
              <div className="text-[11px] text-zinc-400">
                {shot.capture_path ? 'Capture on file — generating re-captures the current view first.' : 'No capture yet — generating captures the current view first.'}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Button size="sm" variant="secondary" disabled={anyBusy} onClick={() => void generateFromComposer('preview')} className="gap-1.5">
                  {workflow.busy === 'preview' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  Preview
                </Button>
                <Button size="sm" disabled={anyBusy} onClick={() => void generateFromComposer('final')} className="gap-1.5">
                  {workflow.busy === 'final' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
                  Final
                </Button>
              </div>
              {genWarnings.length > 0 && (
                <ul className="text-[10px] text-amber-300 space-y-0.5">
                  {genWarnings.map((w, i) => (
                    <li key={i}>• {w}</li>
                  ))}
                </ul>
              )}
              {(queueInfo.active || queueInfo.pendingPosition != null) && (
                <div className="flex items-center gap-2 text-[11px] text-amber-300">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {queueInfo.active
                    ? `Rendering${queueInfo.progress != null ? ` · ${Math.round(queueInfo.progress)}%` : ''}`
                    : `Queued · position ${queueInfo.pendingPosition}`}
                  <button onClick={() => void workflow.cancelJob()} className="ml-auto px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300">
                    Cancel
                  </button>
                </div>
              )}
              {isGenerating && !queueInfo.active && queueInfo.pendingPosition == null && (
                <div className="text-[10px] text-zinc-500">Another shot is rendering — new jobs queue behind it.</div>
              )}
              {queueInfo.active && queueInfo.progress != null && (
                <div className="h-1 rounded bg-zinc-800 overflow-hidden">
                  <div className="h-full bg-violet-500 transition-all" style={{ width: `${Math.min(100, Math.max(0, queueInfo.progress))}%` }} />
                </div>
              )}

              {shot.versions.length > 0 && (
                <div className="space-y-1.5 border-t border-zinc-800 pt-2">
                  <div className="flex items-center text-[10px] text-zinc-500 uppercase tracking-wide">
                    Versions
                    {completeVersions.length >= 2 && (
                      <button
                        onClick={() =>
                          setCompare(prev =>
                            prev
                              ? null
                              : [completeVersions[completeVersions.length - 2].number, completeVersions[completeVersions.length - 1].number],
                          )
                        }
                        className="ml-auto flex items-center gap-1 normal-case px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"
                        aria-pressed={compare !== null}
                      >
                        <Columns2 className="h-3 w-3" /> {compare ? 'Close compare' : 'Compare'}
                      </button>
                    )}
                  </div>
                  {compare && (
                    <div className="grid grid-cols-2 gap-1">
                      {compare.map((number, slot) => (
                        <div key={slot} className="space-y-1">
                          <select
                            value={number}
                            onChange={event => {
                              const next: [number, number] = [...compare]
                              next[slot] = Number(event.target.value)
                              setCompare(next)
                            }}
                            className="w-full bg-zinc-800 border border-zinc-700 rounded px-1 py-0.5 text-[10px] text-zinc-200"
                            aria-label={`Compare slot ${slot + 1}`}
                          >
                            {completeVersions.map(v => (
                              <option key={v.number} value={v.number}>
                                v{v.number} · {v.kind}
                              </option>
                            ))}
                          </select>
                          {versionUrls[number] && <video src={versionUrls[number]} controls muted playsInline preload="metadata" className="w-full rounded bg-black aspect-video" />}
                        </div>
                      ))}
                    </div>
                  )}
                  {[...shot.versions].reverse().map(version => (
                    <div
                      key={version.number}
                      className={`rounded border p-2 space-y-1 ${shot.current_version === version.number ? 'border-violet-700 bg-violet-950/20' : 'border-zinc-800'}`}
                    >
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="font-medium text-zinc-200">
                          v{version.number} · {version.kind}
                        </span>
                        <span className={version.status === 'complete' ? 'text-emerald-400' : version.status === 'failed' ? 'text-red-400' : 'text-amber-400'}>
                          {version.status}
                        </span>
                        <span className="flex-1" />
                        <span className="text-zinc-600">
                          {version.resolution} · {version.duration_seconds.toFixed(0)}s
                          {version.generation_seconds != null ? ` · ${version.generation_seconds.toFixed(0)}s render` : ''}
                        </span>
                      </div>
                      {!compare && version.status === 'complete' && versionUrls[version.number] && (
                        <video src={versionUrls[version.number]} controls playsInline preload="metadata" className="w-full rounded bg-black aspect-video" />
                      )}
                      {version.status === 'failed' && <div className="text-[10px] text-red-400 break-words">{version.error}</div>}
                      <div className="flex gap-1">
                        {version.status === 'complete' && shot.current_version !== version.number && (
                          <button onClick={() => void workflow.promote(version.number)} disabled={anyBusy} className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300">
                            Set current
                          </button>
                        )}
                        {version.status === 'failed' && (
                          <button onClick={() => void generateFromComposer(version.kind)} disabled={anyBusy} className="flex items-center gap-1 px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300">
                            <RefreshCw className="h-2.5 w-2.5" /> Retry
                          </button>
                        )}
                        {version.status === 'complete' && (
                          <button onClick={() => void workflow.sendToTimeline(version)} disabled={anyBusy} className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300">
                            To timeline
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {currentVersion?.status === 'complete' && (
                <div className="space-y-2 border-t border-zinc-800 pt-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Button size="sm" variant={shot.status === 'approved' ? 'default' : 'secondary'} disabled={anyBusy} onClick={() => void workflow.setStatus('approved')} className="gap-1.5">
                      <ThumbsUp className="h-3.5 w-3.5" /> Approve
                    </Button>
                    <Button size="sm" variant="secondary" disabled={anyBusy} onClick={() => void workflow.setStatus('rejected')} className="gap-1.5">
                      <ThumbsDown className="h-3.5 w-3.5" /> Reject
                    </Button>
                  </div>
                  <Button size="sm" disabled={anyBusy} onClick={() => void workflow.sendToTimeline(currentVersion, { replace: workflow.linkedClip !== null })} className="w-full gap-1.5">
                    {workflow.busy === 'timeline' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                    {workflow.linkedClip ? `Replace timeline clip with v${currentVersion.number}` : 'Send to Timeline'}
                  </Button>
                </div>
              )}
            </div>
          </Section>
        </aside>
      </div>
    </div>
  )
}

function KeyframeList({
  title,
  keyframes,
  duration,
  onGoTo,
  onDelete,
  onRetime,
}: {
  title: string
  keyframes: CompositionKeyframe[]
  duration: number
  onGoTo?: (id: string) => void
  onDelete: (id: string) => void
  onRetime: (id: string, time: number) => void
}) {
  if (keyframes.length === 0) return null
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] text-zinc-500">{title}</div>
      <div className="relative h-2 rounded bg-zinc-800">
        {keyframes.map(k => (
          <span
            key={k.id}
            className="absolute -top-0.5 h-3 w-3 rotate-45 bg-violet-400 rounded-[2px]"
            style={{ left: `calc(${Math.min(100, (k.time / Math.max(duration, 0.01)) * 100)}% - 6px)` }}
            title={`${k.time.toFixed(2)}s`}
          />
        ))}
      </div>
      {keyframes.map(k => (
        <div key={k.id} className="flex items-center gap-1 text-[11px] text-zinc-400">
          <Diamond className="h-2.5 w-2.5 text-violet-400" />
          <input
            type="number"
            min={0}
            max={duration}
            step={0.1}
            value={Number(k.time.toFixed(2))}
            onChange={event => onRetime(k.id, Number(event.target.value))}
            className="w-14 bg-zinc-800 border border-zinc-700 rounded px-1 py-0 text-[11px] text-zinc-200 tabular-nums"
            aria-label={`${title} keyframe time`}
          />
          <span>s</span>
          <span className="flex-1" />
          {onGoTo && (
            <button onClick={() => onGoTo(k.id)} className="px-1 py-0.5 rounded hover:bg-zinc-800 text-[10px] text-zinc-300" title="Jump the camera to this keyframe">
              Go to
            </button>
          )}
          <button onClick={() => onDelete(k.id)} className="p-0.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-red-300" aria-label="Delete keyframe">
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

export default ShotComposer
