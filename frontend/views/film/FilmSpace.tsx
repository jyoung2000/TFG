import { Suspense, lazy, useCallback, useMemo, useState } from 'react'
import {
  Clapperboard,
  Clock,
  FileText,
  Layers,
  Loader2,
  MonitorPlay,
  Plus,
  Sparkles,
  Trash2,
  XCircle,
} from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import { Button } from '../../components/ui/button'
import type { FilmScene, FilmShot, VersionKind } from '../../types/film'
import { AssetsPanel } from './AssetsPanel'
import { DirectorBar } from './DirectorBar'
import { ModelsPanel } from './ModelsPanel'
import { ScriptPanel } from './ScriptPanel'
import { ShotCard } from './ShotCard'
import { ShotDetailDrawer } from './ShotDetailDrawer'

// The composer pulls in three.js — keep it out of the main chunk.
const ShotComposer = lazy(() => import('./composer/ShotComposer'))

type FilmTab = 'storyboard' | 'script' | 'assets' | 'models'

const TABS: { id: FilmTab; label: string; icon: React.ReactNode }[] = [
  { id: 'storyboard', label: 'Storyboard', icon: <Clapperboard className="h-3.5 w-3.5" /> },
  { id: 'script', label: 'Script', icon: <FileText className="h-3.5 w-3.5" /> },
  { id: 'assets', label: 'Assets', icon: <Layers className="h-3.5 w-3.5" /> },
  { id: 'models', label: 'Models', icon: <MonitorPlay className="h-3.5 w-3.5" /> },
]

function SceneRow({
  scene,
  sceneNumber,
  selectedShotId,
  onSelectShot,
  onComposeShot,
}: {
  scene: FilmScene
  sceneNumber: number
  selectedShotId: string | null
  onSelectShot: (shot: FilmShot | null) => void
  onComposeShot: (shot: FilmShot) => void
}) {
  const { film, refresh, setFilm } = useFilm()
  const [dragShotId, setDragShotId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState<string | null>(null)

  const shots = useMemo(() => [...scene.shots].sort((a, b) => a.order - b.order), [scene.shots])
  const projectId = film?.id ?? ''

  const addShot = useCallback(async () => {
    if (!projectId) return
    await filmApi.createShot(projectId, scene.id, {})
    await refresh()
  }, [projectId, scene.id, refresh])

  const duplicateShot = useCallback(
    async (shot: FilmShot) => {
      if (!projectId) return
      await filmApi.duplicateShot(projectId, scene.id, shot.id)
      await refresh()
    },
    [projectId, scene.id, refresh],
  )

  const deleteShot = useCallback(
    async (shot: FilmShot) => {
      if (!projectId) return
      if (!window.confirm(`Delete ${shot.title || 'this shot'}?`)) return
      await filmApi.deleteShot(projectId, scene.id, shot.id)
      if (selectedShotId === shot.id) onSelectShot(null)
      await refresh()
    },
    [projectId, scene.id, selectedShotId, onSelectShot, refresh],
  )

  const deleteScene = useCallback(async () => {
    if (!projectId) return
    if (!window.confirm(`Delete ${scene.title || 'this scene'} and its ${shots.length} shots?`)) return
    await filmApi.deleteScene(projectId, scene.id)
    onSelectShot(null)
    await refresh()
  }, [projectId, scene.id, scene.title, shots.length, onSelectShot, refresh])

  const generateScene = useCallback(
    async (kind: VersionKind) => {
      if (!projectId) return
      await filmApi.generateBatch(projectId, { kind, scene_id: scene.id })
      await refresh()
    },
    [projectId, scene.id, refresh],
  )

  const dropOn = useCallback(
    async (targetShot: FilmShot) => {
      if (!projectId || !dragShotId || dragShotId === targetShot.id) return
      const ids = shots.map(s => s.id)
      const from = ids.indexOf(dragShotId)
      const to = ids.indexOf(targetShot.id)
      if (from < 0 || to < 0) return
      ids.splice(to, 0, ...ids.splice(from, 1))
      const updatedScene = await filmApi.reorderShots(projectId, scene.id, ids)
      if (film) {
        setFilm({
          ...film,
          scenes: film.scenes.map(s => (s.id === updatedScene.id ? updatedScene : s)),
        })
      }
      setDragShotId(null)
    },
    [projectId, dragShotId, shots, scene.id, film, setFilm],
  )

  const saveTitle = useCallback(async () => {
    if (!projectId || titleDraft === null || titleDraft === scene.title) {
      setTitleDraft(null)
      return
    }
    await filmApi.updateScene(projectId, scene.id, { title: titleDraft })
    setTitleDraft(null)
    await refresh()
  }, [projectId, scene.id, scene.title, titleDraft, refresh])

  const sceneDuration = shots.reduce((sum, s) => sum + s.duration_seconds, 0)
  const gap = film?.settings.inter_shot_gap_seconds ?? 0

  return (
    <div className="border-b border-zinc-800/70">
      <div className="flex items-center gap-2 px-4 pt-3 pb-2">
        <span className="text-[10px] font-bold text-zinc-600 tabular-nums">
          {String(sceneNumber).padStart(2, '0')}
        </span>
        {titleDraft !== null ? (
          <input
            autoFocus
            value={titleDraft}
            onChange={e => setTitleDraft(e.target.value)}
            onBlur={() => void saveTitle()}
            onKeyDown={e => {
              if (e.key === 'Enter') void saveTitle()
              if (e.key === 'Escape') setTitleDraft(null)
            }}
            className="bg-zinc-800 border border-violet-700 rounded px-2 py-0.5 text-sm text-white focus:outline-none"
          />
        ) : (
          <button
            onDoubleClick={() => setTitleDraft(scene.title)}
            className="text-sm font-semibold text-white hover:text-violet-300"
            title="Double-click to rename"
          >
            {scene.title || `Scene ${sceneNumber}`}
          </button>
        )}
        <span className="flex items-center gap-1 text-[10px] text-zinc-600">
          <Clock className="h-3 w-3" />
          {sceneDuration.toFixed(1)}s · {shots.length} shots
        </span>
        <span className="flex-1" />
        <button
          onClick={() => void generateScene('preview')}
          className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"
          title="Queue preview generation for every shot in the scene"
        >
          <Sparkles className="h-3 w-3" /> Generate scene
        </button>
        <button
          onClick={() => void deleteScene()}
          className="p-1 rounded hover:bg-red-950/60 text-zinc-600 hover:text-red-400"
          title="Delete scene"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Shot strip with timing gaps */}
      <div className="flex items-stretch gap-2 px-4 pb-3 overflow-x-auto">
        {shots.map((shot, index) => (
          <div key={shot.id} className="flex items-center gap-2">
            {index > 0 && gap > 0 && (
              <div className="shrink-0 text-[9px] text-zinc-700 rotate-90 whitespace-nowrap w-3 text-center">
                {gap.toFixed(1)}s
              </div>
            )}
            <ShotCard
              film={film!}
              shot={shot}
              sceneNumber={sceneNumber}
              shotNumber={index + 1}
              isSelected={selectedShotId === shot.id}
              onOpen={() => onSelectShot(shot)}
              onCompose={() => onComposeShot(shot)}
              onDuplicate={() => void duplicateShot(shot)}
              onDelete={() => void deleteShot(shot)}
              onDragStart={() => setDragShotId(shot.id)}
              onDragOver={e => e.preventDefault()}
              onDrop={e => {
                e.preventDefault()
                void dropOn(shot)
              }}
            />
          </div>
        ))}
        <button
          onClick={() => void addShot()}
          className="w-24 shrink-0 rounded-lg border border-dashed border-zinc-800 hover:border-violet-700 flex flex-col items-center justify-center gap-1 text-zinc-600 hover:text-violet-400 min-h-[9rem]"
        >
          <Plus className="h-4 w-4" />
          <span className="text-[10px]">Add shot</span>
        </button>
      </div>
    </div>
  )
}

export function FilmSpace() {
  const { film, isLoading, error, refresh, queue, isGenerating } = useFilm()
  const [tab, setTab] = useState<FilmTab>('storyboard')
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [composerShotId, setComposerShotId] = useState<string | null>(null)

  const scenes = useMemo(
    () => (film ? [...film.scenes].sort((a, b) => a.order - b.order) : []),
    [film],
  )

  const selected = useMemo(() => {
    if (!film || !selectedShotId) return null
    for (const scene of film.scenes) {
      const shot = scene.shots.find(s => s.id === selectedShotId)
      if (shot) return { scene, shot }
    }
    return null
  }, [film, selectedShotId])

  const composerTarget = useMemo(() => {
    if (!film || !composerShotId) return null
    for (const scene of film.scenes) {
      const shot = scene.shots.find(s => s.id === composerShotId)
      if (shot) return { scene, shot }
    }
    return null
  }, [film, composerShotId])

  const addScene = useCallback(async () => {
    if (!film) return
    await filmApi.createScene(film.id, {})
    await refresh()
  }, [film, refresh])

  const generateAll = useCallback(async () => {
    if (!film) return
    await filmApi.generateBatch(film.id, { kind: 'preview' })
    await refresh()
  }, [film, refresh])

  const cancelQueue = useCallback(async () => {
    await filmApi.cancelQueue()
    await refresh()
  }, [refresh])

  const totalDuration = scenes.reduce(
    (sum, scene) => sum + scene.shots.reduce((s, shot) => s + shot.duration_seconds, 0),
    0,
  )
  const totalShots = scenes.reduce((sum, scene) => sum + scene.shots.length, 0)

  if (isLoading && !film) {
    return (
      <div className="h-full flex items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 text-violet-500 animate-spin" />
      </div>
    )
  }

  if (error && !film) {
    return (
      <div className="h-full flex items-center justify-center bg-background">
        <div className="text-center max-w-sm">
          <p className="text-sm text-red-400 mb-2">Could not load the film workspace</p>
          <p className="text-xs text-zinc-500 mb-3">{error}</p>
          <Button size="sm" onClick={() => void refresh()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Sub-tab bar + queue status */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        <div className="flex items-center gap-0.5 bg-zinc-900 rounded-lg p-0.5">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                tab === t.id ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        {isGenerating && (
          <div className="flex items-center gap-2 text-[11px] text-amber-300">
            <Loader2 className="h-3 w-3 animate-spin" />
            {queue.active
              ? `Generating ${queue.active.shot_title || 'shot'} (${queue.active.kind})`
              : 'Queued…'}
            {queue.pending.length > 0 && <span>+{queue.pending.length} queued</span>}
            <button
              onClick={() => void cancelQueue()}
              className="flex items-center gap-0.5 text-zinc-500 hover:text-red-400"
            >
              <XCircle className="h-3 w-3" /> Cancel
            </button>
          </div>
        )}
        {tab === 'storyboard' && (
          <>
            <span className="text-[11px] text-zinc-600 tabular-nums">
              {scenes.length} scenes · {totalShots} shots · {totalDuration.toFixed(1)}s
            </span>
            <Button size="sm" variant="secondary" onClick={() => void addScene()} className="gap-1">
              <Plus className="h-3.5 w-3.5" /> Scene
            </Button>
            <Button
              size="sm"
              onClick={() => void generateAll()}
              disabled={totalShots === 0 || isGenerating}
              className="gap-1"
              title="Queue preview generation for the whole storyboard"
            >
              <Sparkles className="h-3.5 w-3.5" /> Generate all
            </Button>
          </>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 min-w-0 overflow-y-auto">
          {tab === 'storyboard' &&
            (scenes.length > 0 ? (
              scenes.map((scene, index) => (
                <SceneRow
                  key={scene.id}
                  scene={scene}
                  sceneNumber={index + 1}
                  selectedShotId={selectedShotId}
                  onSelectShot={shot => setSelectedShotId(shot?.id ?? null)}
                  onComposeShot={shot => setComposerShotId(shot.id)}
                />
              ))
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center max-w-md">
                  <Clapperboard className="h-10 w-10 text-zinc-800 mx-auto mb-3" />
                  <h3 className="text-sm font-semibold text-zinc-300">Storyboard is empty</h3>
                  <p className="text-xs text-zinc-600 mt-1 mb-4">
                    Write a script and generate a draft storyboard, or start adding scenes by hand.
                    Every shot can then be composed in 3D, captured, and generated with the local
                    model.
                  </p>
                  <div className="flex items-center justify-center gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setTab('script')} className="gap-1">
                      <FileText className="h-3.5 w-3.5" /> Write script
                    </Button>
                    <Button size="sm" onClick={() => void addScene()} className="gap-1">
                      <Plus className="h-3.5 w-3.5" /> First scene
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          {tab === 'script' && <ScriptPanel onStoryboardCreated={() => setTab('storyboard')} />}
          {tab === 'assets' && <AssetsPanel />}
          {tab === 'models' && <ModelsPanel />}
        </div>

        {tab === 'storyboard' && selected && (
          <ShotDetailDrawer
            scene={selected.scene}
            shot={selected.shot}
            onClose={() => setSelectedShotId(null)}
            onCompose={() => setComposerShotId(selected.shot.id)}
          />
        )}
      </div>

      {tab === 'storyboard' && (
        <DirectorBar selectedSceneId={selected?.scene.id ?? null} selectedShotId={selectedShotId} />
      )}

      {/* Shot Composer overlay */}
      {composerTarget && film && (
        <Suspense
          fallback={
            <div className="fixed inset-0 z-50 bg-zinc-950 flex items-center justify-center">
              <Loader2 className="h-6 w-6 text-violet-500 animate-spin" />
            </div>
          }
        >
          <ShotComposer
            projectId={film.id}
            scene={composerTarget.scene}
            shot={composerTarget.shot}
            onClose={() => {
              setComposerShotId(null)
              void refresh()
            }}
          />
        </Suspense>
      )}
    </div>
  )
}
