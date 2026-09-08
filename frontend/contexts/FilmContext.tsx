import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { filmApi } from '../lib/film-api'
import { logger } from '../lib/logger'
import type {
  ContinuityLevel,
  FilmCapabilities,
  FilmProject,
  FilmQueue,
  FilmScene,
  FilmShot,
  ProjectContinuity,
} from '../types/film'
import { useProjects } from './ProjectContext'

/** A request from elsewhere in the app (editor, Gen Space) to open a shot in the storyboard. */
export interface ShotFocusRequest {
  shotId: string
  /** Also open the Shot Composer for it. */
  compose?: boolean
}

interface FilmContextType {
  film: FilmProject | null
  isLoading: boolean
  error: string | null
  /** Re-fetch the film project from the backend (the single source of truth). */
  refresh: () => Promise<FilmProject | null>
  /** Optimistically replace the cached film project (after a mutation returned fresh data). */
  setFilm: (film: FilmProject) => void
  queue: FilmQueue
  capabilities: FilmCapabilities | null
  refreshCapabilities: () => Promise<void>
  /** True while any film generation is active or pending. */
  isGenerating: boolean
  findShot: (shotId: string) => { scene: FilmScene; shot: FilmShot } | null
  /** Project-wide continuity summary (refreshed with the project). */
  continuity: ProjectContinuity | null
  continuityLevelFor: (shotId: string) => ContinuityLevel | null
  /** Keep the card markers in step with a fresh per-shot report (drawer fetch/fix). */
  setShotContinuity: (shotId: string, level: ContinuityLevel, warningCount: number) => void
  setQueue: (queue: FilmQueue) => void
  /** Undo/redo over structural project edits (scenes, shots, assets, script, settings, compositions). */
  undo: () => Promise<void>
  redo: () => Promise<void>
  canUndo: boolean
  canRedo: boolean
  historyNote: string
  /** Ask the storyboard to select (and optionally compose) a shot once it is showing. */
  focusShot: (request: ShotFocusRequest) => void
  pendingFocus: ShotFocusRequest | null
  clearPendingFocus: () => void
}

const FilmContext = createContext<FilmContextType | null>(null)

const EMPTY_QUEUE: FilmQueue = { active: null, pending: [], paused: false, progress: null, phase: '' }
const HISTORY_LIMIT = 40

/**
 * A signature of the project's user-authored structure. Generation progress
 * (version status/output, shot status) is deliberately excluded so the polling
 * refresh during a render does not create undo steps.
 */
function structuralSignature(project: FilmProject): string {
  return JSON.stringify({
    name: project.name,
    script: project.script.content,
    settings: project.settings,
    assets: project.assets,
    pose_library: project.pose_library,
    scenes: project.scenes.map(scene => ({
      ...scene,
      shots: scene.shots.map(shot => {
        const { versions: _versions, current_version: _current, status: _status, updated_at: _updated, ...rest } = shot
        return rest
      }),
    })),
  })
}

export function FilmProvider({ children }: { children: React.ReactNode }) {
  const { currentProjectId, currentTab } = useProjects()
  const [film, setFilmState] = useState<FilmProject | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queue, setQueue] = useState<FilmQueue>(EMPTY_QUEUE)
  const [capabilities, setCapabilities] = useState<FilmCapabilities | null>(null)
  const [continuity, setContinuity] = useState<ProjectContinuity | null>(null)
  const [pendingFocus, setPendingFocus] = useState<ShotFocusRequest | null>(null)
  const [historyNote, setHistoryNote] = useState('')
  const [historySize, setHistorySize] = useState({ undo: 0, redo: 0 })
  const projectIdRef = useRef<string | null>(null)
  projectIdRef.current = currentProjectId

  // Undo/redo stacks of project snapshots, per project. A snapshot is pushed
  // whenever a refreshed project differs structurally from the last one seen.
  const undoStackRef = useRef<FilmProject[]>([])
  const redoStackRef = useRef<FilmProject[]>([])
  const lastSeenRef = useRef<{ projectId: string; project: FilmProject; signature: string } | null>(null)
  const restoringRef = useRef(false)
  // Latest-wins ordering for project loads: a poll that started before an
  // undo/redo (or a newer refresh) must not overwrite the fresher state or be
  // recorded as an edit when it finally arrives.
  const loadEpochRef = useRef(0)

  const syncHistorySize = useCallback(() => {
    setHistorySize({ undo: undoStackRef.current.length, redo: redoStackRef.current.length })
  }, [])

  const recordSnapshot = useCallback(
    (projectId: string, project: FilmProject) => {
      const signature = structuralSignature(project)
      const last = lastSeenRef.current
      if (!last || last.projectId !== projectId) {
        undoStackRef.current = []
        redoStackRef.current = []
      } else if (last.signature !== signature && !restoringRef.current) {
        undoStackRef.current = [...undoStackRef.current.slice(-(HISTORY_LIMIT - 1)), last.project]
        redoStackRef.current = []
      }
      lastSeenRef.current = { projectId, project, signature }
      syncHistorySize()
    },
    [syncHistorySize],
  )

  const refresh = useCallback(async (): Promise<FilmProject | null> => {
    const projectId = projectIdRef.current
    if (!projectId) return null
    const epoch = ++loadEpochRef.current
    try {
      const project = await filmApi.getProject(projectId)
      if (projectIdRef.current === projectId && epoch === loadEpochRef.current) {
        setFilmState(project)
        setError(null)
        recordSnapshot(projectId, project)
      }
      // Continuity is derived state; a failure here must not hide the project.
      void filmApi
        .projectContinuity(projectId)
        .then(summary => {
          if (projectIdRef.current === projectId) setContinuity(summary)
        })
        .catch(() => {})
      return project
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      logger.error(`Failed to load film project: ${message}`)
      if (projectIdRef.current === projectId) setError(message)
      return null
    }
  }, [recordSnapshot])

  const refreshCapabilities = useCallback(async () => {
    try {
      setCapabilities(await filmApi.capabilities())
    } catch (e) {
      logger.warn(`Failed to load film capabilities: ${e}`)
    }
  }, [])

  // Load the film facet whenever the storyboard tab of a project opens.
  useEffect(() => {
    if (!currentProjectId || currentTab !== 'storyboard') return
    let cancelled = false
    setIsLoading(true)
    void (async () => {
      await refresh()
      await refreshCapabilities()
      if (!cancelled) setIsLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [currentProjectId, currentTab, refresh, refreshCapabilities])

  // Poll the generation queue while anything is running, and refresh the
  // project when the queue drains (statuses/versions will have changed).
  const wasBusyRef = useRef(false)
  useEffect(() => {
    if (currentTab !== 'storyboard') return
    const interval = setInterval(async () => {
      try {
        const next = await filmApi.queue()
        setQueue(next)
        const busy = next.active !== null || next.pending.length > 0
        if (busy || wasBusyRef.current) {
          await refresh()
        }
        wasBusyRef.current = busy
      } catch {
        // Backend briefly unreachable; keep the last state.
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [currentTab, refresh])

  const restore = useCallback(
    async (snapshot: FilmProject, direction: 'undo' | 'redo') => {
      const projectId = projectIdRef.current
      if (!projectId) return
      restoringRef.current = true
      loadEpochRef.current++ // in-flight polls are stale from here on
      try {
        const project = await filmApi.replaceProject(projectId, snapshot)
        loadEpochRef.current++
        setFilmState(project)
        lastSeenRef.current = { projectId, project, signature: structuralSignature(project) }
        setHistoryNote(direction === 'undo' ? 'Undone' : 'Redone')
        void filmApi
          .projectContinuity(projectId)
          .then(summary => setContinuity(summary))
          .catch(() => {})
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e)
        setHistoryNote(`${direction === 'undo' ? 'Undo' : 'Redo'} failed: ${message}`)
        throw e
      } finally {
        restoringRef.current = false
        syncHistorySize()
      }
    },
    [syncHistorySize],
  )

  const undo = useCallback(async () => {
    const previous = undoStackRef.current[undoStackRef.current.length - 1]
    const current = lastSeenRef.current?.project
    if (!previous || !current) return
    undoStackRef.current = undoStackRef.current.slice(0, -1)
    redoStackRef.current = [...redoStackRef.current, current]
    try {
      await restore(previous, 'undo')
    } catch {
      // Put the stacks back the way they were so the user can retry.
      undoStackRef.current = [...undoStackRef.current, previous]
      redoStackRef.current = redoStackRef.current.slice(0, -1)
      syncHistorySize()
    }
  }, [restore, syncHistorySize])

  const redo = useCallback(async () => {
    const next = redoStackRef.current[redoStackRef.current.length - 1]
    const current = lastSeenRef.current?.project
    if (!next || !current) return
    redoStackRef.current = redoStackRef.current.slice(0, -1)
    undoStackRef.current = [...undoStackRef.current, current]
    try {
      await restore(next, 'redo')
    } catch {
      redoStackRef.current = [...redoStackRef.current, next]
      undoStackRef.current = undoStackRef.current.slice(0, -1)
      syncHistorySize()
    }
  }, [restore, syncHistorySize])

  const findShot = useCallback(
    (shotId: string): { scene: FilmScene; shot: FilmShot } | null => {
      if (!film) return null
      for (const scene of film.scenes) {
        const shot = scene.shots.find(s => s.id === shotId)
        if (shot) return { scene, shot }
      }
      return null
    },
    [film],
  )

  const setFilm = useCallback(
    (next: FilmProject) => {
      setFilmState(next)
      if (projectIdRef.current) recordSnapshot(projectIdRef.current, next)
    },
    [recordSnapshot],
  )

  const continuityLevelFor = useCallback(
    (shotId: string): ContinuityLevel | null => continuity?.shots.find(s => s.shot_id === shotId)?.level ?? null,
    [continuity],
  )

  const setShotContinuity = useCallback((shotId: string, level: ContinuityLevel, warningCount: number) => {
    setContinuity(prev => {
      if (!prev) return prev
      const existing = prev.shots.find(s => s.shot_id === shotId)
      if (existing && existing.level === level && existing.warning_count === warningCount) return prev
      const shots = existing
        ? prev.shots.map(s => (s.shot_id === shotId ? { ...s, level, warning_count: warningCount } : s))
        : [...prev.shots, { shot_id: shotId, scene_id: '', level, warning_count: warningCount }]
      const rank: Record<ContinuityLevel, number> = { good: 0, minor: 1, significant: 2, broken: 3 }
      const worst = shots.reduce<ContinuityLevel>((acc, s) => (rank[s.level] > rank[acc] ? s.level : acc), 'good')
      const counts: Record<string, number> = { good: 0, minor: 0, significant: 0, broken: 0 }
      for (const s of shots) counts[s.level] = (counts[s.level] ?? 0) + 1
      return { level: worst, shots, counts }
    })
  }, [])

  const focusShot = useCallback((request: ShotFocusRequest) => setPendingFocus(request), [])
  const clearPendingFocus = useCallback(() => setPendingFocus(null), [])

  const isGenerating = queue.active !== null || queue.pending.length > 0

  const value = useMemo(
    () => ({
      film,
      isLoading,
      error,
      refresh,
      setFilm,
      queue,
      setQueue,
      capabilities,
      refreshCapabilities,
      isGenerating,
      findShot,
      continuity,
      continuityLevelFor,
      setShotContinuity,
      undo,
      redo,
      canUndo: historySize.undo > 0,
      canRedo: historySize.redo > 0,
      historyNote,
      focusShot,
      pendingFocus,
      clearPendingFocus,
    }),
    [
      film,
      isLoading,
      error,
      refresh,
      setFilm,
      queue,
      capabilities,
      refreshCapabilities,
      isGenerating,
      findShot,
      continuity,
      continuityLevelFor,
      setShotContinuity,
      undo,
      redo,
      historySize,
      historyNote,
      focusShot,
      pendingFocus,
      clearPendingFocus,
    ],
  )

  return <FilmContext.Provider value={value}>{children}</FilmContext.Provider>
}

export function useFilm() {
  const context = useContext(FilmContext)
  if (!context) {
    throw new Error('useFilm must be used within a FilmProvider')
  }
  return context
}
