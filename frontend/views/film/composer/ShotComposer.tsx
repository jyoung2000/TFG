import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Aperture,
  Box,
  Camera,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Cylinder,
  Eye,
  EyeOff,
  Loader2,
  PersonStanding,
  Save,
  Trash2,
  Triangle,
  X,
} from 'lucide-react'
import { Button } from '../../../components/ui/button'
import { filmApi } from '../../../lib/film-api'
import { logger } from '../../../lib/logger'
import type {
  CameraMove,
  CompositionObject,
  CompositionObjectType,
  FigureVariant,
  FilmAsset,
  FilmScene,
  FilmShot,
  ShotFraming,
  Vec3,
} from '../../../types/film'
import {
  CAMERA_ANGLES,
  CAMERA_ELEVATIONS,
  CAMERA_MOVES,
  COMPOSITIONS,
  SHOT_SIZES,
} from '../../../types/film'
import { useFilm } from '../../../contexts/FilmContext'
import { ComposerScene } from './composerScene'
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
    transform: { position: [objectCounter * 0.9 - 1, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    pose: {},
    figure_variant: variant,
    color: '',
    keyframes: [],
    fov: null,
  }
}

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
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-zinc-800">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-zinc-300 uppercase tracking-wide hover:bg-zinc-800/60"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title}
      </button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  )
}

export function ShotComposer({ projectId, scene, shot, onClose }: ShotComposerProps) {
  const { film, refresh } = useFilm()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<ComposerScene | null>(null)

  const [objects, setObjects] = useState<CompositionObject[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [framing, setFraming] = useState<ShotFraming>(shot.framing)
  const [cameraMove, setCameraMove] = useState<CameraMove>(shot.camera_move)
  const [previewT, setPreviewT] = useState(0)
  const [motionPreviewOn, setMotionPreviewOn] = useState(false)
  const [selectedJoint, setSelectedJoint] = useState<string>('l_arm')
  const [jointEuler, setJointEuler] = useState<Vec3>([0, 0, 0])
  const [busy, setBusy] = useState<'save' | 'capture' | null>(null)
  const [statusNote, setStatusNote] = useState('')
  const [poseNameDraft, setPoseNameDraft] = useState('')

  const characters = useMemo(
    () => (film?.assets ?? []).filter(a => a.kind === 'character'),
    [film],
  )
  const poseLibrary: PoseEntry[] = useMemo(
    () => mergePoseLibrary(film?.pose_library ?? []),
    [film],
  )

  // ---- Scene bootstrap --------------------------------------------------

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const composer = new ComposerScene(canvas)
    sceneRef.current = composer
    composer.onSelect = id => setSelectedId(id)

    // Hydrate from the saved composition, or seed from the shot's cast.
    if (shot.composition && shot.composition.objects.length > 0) {
      composer.hydrate(shot.composition)
      setObjects(shot.composition.objects)
      setCameraMove(shot.composition.camera_move)
      setFraming(shot.composition.framing)
    } else {
      const seeded: CompositionObject[] = []
      shot.characters.forEach((shotCharacter, index) => {
        const asset = film?.assets.find(a => a.id === shotCharacter.asset_id)
        const object = newObject('figure', asset?.name ?? `Character ${index + 1}`)
        object.asset_id = shotCharacter.asset_id
        object.transform.position = [index * 1.2 - (shot.characters.length - 1) * 0.6, 0, 0]
        seeded.push(object)
        composer.addObject(object)
      })
      if (seeded.length === 0) {
        const object = newObject('figure', 'Character 1')
        seeded.push(object)
        composer.addObject(object)
      }
      setObjects(seeded)
      composer.applyFraming(shot.framing)
    }

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

  // Re-solve the camera whenever framing changes.
  useEffect(() => {
    sceneRef.current?.applyFraming(framing)
  }, [framing])

  // Sync joint sliders when the selection or joint changes.
  useEffect(() => {
    if (!selectedId) return
    const pose = sceneRef.current?.readPoseOf(selectedId) ?? {}
    setJointEuler(pose[selectedJoint] ?? [0, 0, 0])
  }, [selectedId, selectedJoint])

  // Motion preview scrubber drives the camera along its keyframes.
  useEffect(() => {
    const composer = sceneRef.current
    if (!composer) return
    if (motionPreviewOn && composer.cameraKeyframes.length > 1) {
      composer.setPreviewTime(previewT * shot.duration_seconds)
    } else {
      composer.setPreviewTime(null)
    }
  }, [motionPreviewOn, previewT, shot.duration_seconds])

  // ---- Object actions ---------------------------------------------------

  const addFigure = useCallback(
    (variant: FigureVariant, asset?: FilmAsset) => {
      const composer = sceneRef.current
      if (!composer) return
      const object = newObject('figure', asset?.name ?? `Character ${objects.length + 1}`, variant)
      if (asset) object.asset_id = asset.id
      composer.addObject(object)
      setObjects(prev => [...prev, object])
      composer.select(object.id)
    },
    [objects.length],
  )

  const addPrimitive = useCallback((type: CompositionObjectType, label: string) => {
    const composer = sceneRef.current
    if (!composer) return
    const object = newObject(type, label)
    composer.addObject(object)
    setObjects(prev => [...prev, object])
    composer.select(object.id)
  }, [])

  const removeSelected = useCallback(() => {
    if (!selectedId) return
    sceneRef.current?.removeObject(selectedId)
    setObjects(prev => prev.filter(o => o.id !== selectedId))
  }, [selectedId])

  const toggleVisible = useCallback((id: string) => {
    const entity = sceneRef.current?.getEntity(id)
    if (!entity) return
    entity.node.visible = !entity.node.visible
    setObjects(prev => prev.map(o => (o.id === id ? { ...o, visible: entity.node.visible } : o)))
  }, [])

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

  const rotateSelected = useCallback(
    (degrees: number) => {
      if (!selectedId) return
      const entity = sceneRef.current?.getEntity(selectedId)
      if (entity) {
        sceneRef.current?.setObjectRotationY(
          selectedId,
          entity.node.rotation.y + (degrees * Math.PI) / 180,
        )
      }
    },
    [selectedId],
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

  // ---- OTS relationship -------------------------------------------------

  const needsOts = framing.camera_angle === 'ots' || framing.camera_angle === 'pov'
  const figureObjects = objects.filter(o => o.type === 'figure')

  // ---- Save / capture ---------------------------------------------------

  const serialize = useCallback(() => {
    const composer = sceneRef.current
    if (!composer) return null
    if (cameraMove !== 'static' && composer.cameraKeyframes.length < 2) {
      composer.applyCameraMove(cameraMove, shot.duration_seconds)
    }
    return composer.serialize(framing, cameraMove, shot.duration_seconds)
  }, [framing, cameraMove, shot.duration_seconds])

  const saveComposition = useCallback(async () => {
    const composition = serialize()
    if (!composition) return
    setBusy('save')
    try {
      await filmApi.updateShot(projectId, scene.id, shot.id, { composition })
      await refresh()
      setStatusNote('Composition saved')
    } catch (e) {
      logger.error(`Save composition failed: ${e}`)
      setStatusNote(`Save failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [serialize, projectId, scene.id, shot.id, refresh])

  const captureShot = useCallback(async () => {
    const composer = sceneRef.current
    const composition = serialize()
    if (!composer || !composition) return
    setBusy('capture')
    try {
      composer.setPreviewTime(motionPreviewOn ? 0 : null)
      const dataUrl = composer.capture(1280, 720)
      await filmApi.captureShot(projectId, scene.id, shot.id, dataUrl, composition)
      await refresh()
      setStatusNote('Shot captured — reference image saved')
    } catch (e) {
      logger.error(`Capture failed: ${e}`)
      setStatusNote(`Capture failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [serialize, motionPreviewOn, projectId, scene.id, shot.id, refresh])

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

  return (
    <div className="fixed inset-0 z-50 bg-zinc-950 flex flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-800 bg-zinc-900/80">
        <Aperture className="h-4 w-4 text-violet-400" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white truncate">
            Shot Composer — {scene.title} · {shot.title || `Shot ${shot.order + 1}`}
          </div>
          <div className="text-[11px] text-zinc-500">
            Drag characters on the floor · orbit with the mouse · the inset is the shot camera
          </div>
        </div>
        {statusNote && <span className="text-xs text-zinc-400">{statusNote}</span>}
        <Button
          size="sm"
          variant="secondary"
          onClick={saveComposition}
          disabled={busy !== null}
          className="gap-1.5"
        >
          {busy === 'save' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save
        </Button>
        <Button size="sm" onClick={captureShot} disabled={busy !== null} className="gap-1.5">
          {busy === 'capture' ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Camera className="h-3.5 w-3.5" />
          )}
          Capture Shot
        </Button>
        <button onClick={onClose} className="p-2 rounded hover:bg-zinc-800 text-zinc-400">
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* Left: scene tree */}
        <aside className="w-56 border-r border-zinc-800 bg-zinc-900/60 flex flex-col">
          <div className="px-3 py-2 text-xs font-semibold text-zinc-400 uppercase tracking-wide">
            Scene
          </div>
          <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
            {objects.map(object => (
              <div
                key={object.id}
                className={`flex items-center gap-1.5 px-2 py-1.5 rounded text-xs cursor-pointer ${
                  selectedId === object.id
                    ? 'bg-violet-600/30 text-white'
                    : 'text-zinc-300 hover:bg-zinc-800'
                }`}
                onClick={() => sceneRef.current?.select(object.id)}
                onDoubleClick={() => sceneRef.current?.focusOn(object.id)}
              >
                {objectIcon(object.type)}
                <span className="flex-1 truncate">{object.name}</span>
                <button
                  onClick={event => {
                    event.stopPropagation()
                    toggleVisible(object.id)
                  }}
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
            {selectedId && (
              <button
                onClick={removeSelected}
                className="w-full flex items-center justify-center gap-1 px-2 py-1 rounded bg-red-950/60 hover:bg-red-900/60 text-[11px] text-red-300"
              >
                <Trash2 className="h-3 w-3" /> Remove selected
              </button>
            )}
          </div>
        </aside>

        {/* Center: viewport */}
        <div ref={containerRef} className="flex-1 relative min-w-0">
          <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
          {selectedId && (
            <div className="absolute top-3 left-3 flex items-center gap-1 bg-zinc-900/85 rounded-lg px-2 py-1.5 border border-zinc-700">
              <span className="text-[11px] text-zinc-400 mr-1">Rotate</span>
              {[-45, -15, 15, 45].map(deg => (
                <button
                  key={deg}
                  onClick={() => rotateSelected(deg)}
                  className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[11px] text-zinc-200"
                >
                  {deg > 0 ? `+${deg}°` : `${deg}°`}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right: inspector panels */}
        <aside className="w-72 border-l border-zinc-800 bg-zinc-900/60 overflow-y-auto">
          <Section title="Shot" defaultOpen>
            <div className="space-y-2.5">
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Shot size</div>
                <PresetGrid
                  options={SHOT_SIZES}
                  value={framing.shot_size}
                  onChange={id => setFraming(f => ({ ...f, shot_size: id }))}
                />
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Angle</div>
                <PresetGrid
                  options={CAMERA_ANGLES}
                  value={framing.camera_angle}
                  onChange={id => setFraming(f => ({ ...f, camera_angle: id }))}
                />
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Elevation</div>
                <PresetGrid
                  options={CAMERA_ELEVATIONS}
                  value={framing.camera_elevation}
                  onChange={id => setFraming(f => ({ ...f, camera_elevation: id }))}
                />
              </div>
              <div>
                <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Composition</div>
                <PresetGrid
                  options={COMPOSITIONS}
                  value={framing.composition}
                  onChange={id => setFraming(f => ({ ...f, composition: id }))}
                />
              </div>
              {needsOts && (
                <div className="space-y-1.5 border border-zinc-800 rounded p-2">
                  <div className="text-[10px] text-violet-300 uppercase tracking-wide">
                    Over-the-shoulder relationship
                  </div>
                  <label className="block text-[11px] text-zinc-400">
                    Foreground (camera behind)
                    <select
                      value={framing.ots_foreground_id ?? ''}
                      onChange={event =>
                        setFraming(f => ({ ...f, ots_foreground_id: event.target.value || null }))
                      }
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
                      onChange={event =>
                        setFraming(f => ({ ...f, ots_subject_id: event.target.value || null }))
                      }
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
                </div>
              )}
            </div>
          </Section>

          <Section title="Camera">
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
            <p className="text-[10px] text-zinc-600 mt-1">
              Presets re-solve the camera. Narrow FOV = longer lens.
            </p>
          </Section>

          <Section title="Pose">
            {selectedId && sceneRef.current?.getEntity(selectedId)?.rig ? (
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
                      <span className="w-8 text-right tabular-nums">
                        {jointEuler[index as 0 | 1 | 2].toFixed(0)}°
                      </span>
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
                  >
                    <Check className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-zinc-600">Select a character figure to pose it.</p>
            )}
          </Section>

          <Section title="Motion">
            <div className="space-y-2">
              <PresetGrid
                options={CAMERA_MOVES}
                value={cameraMove}
                onChange={id => {
                  setCameraMove(id)
                  sceneRef.current?.applyCameraMove(id, shot.duration_seconds)
                  setMotionPreviewOn(id !== 'static')
                  setPreviewT(0)
                }}
              />
              {cameraMove !== 'static' && (
                <div className="space-y-1">
                  <label className="flex items-center gap-2 text-[11px] text-zinc-400">
                    <input
                      type="checkbox"
                      checked={motionPreviewOn}
                      onChange={event => setMotionPreviewOn(event.target.checked)}
                    />
                    Preview move
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={previewT}
                    onChange={event => setPreviewT(Number(event.target.value))}
                    className="w-full"
                    disabled={!motionPreviewOn}
                  />
                  <div className="text-[10px] text-zinc-600">
                    0s — {(previewT * shot.duration_seconds).toFixed(1)}s —{' '}
                    {shot.duration_seconds.toFixed(1)}s
                  </div>
                </div>
              )}
            </div>
          </Section>
        </aside>
      </div>
    </div>
  )
}

export default ShotComposer
