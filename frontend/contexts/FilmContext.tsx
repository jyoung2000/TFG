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
}

const FilmContext = createContext<FilmContextType | null>(null)

const EMPTY_QUEUE: FilmQueue = { active: null, pending: [], paused: false, progress: null, phase: '' }

export function FilmProvider({ children }: { children: React.ReactNode }) {
  const { currentProjectId, currentTab } = useProjects()
  const [film, setFilmState] = useState<FilmProject | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queue, setQueue] = useState<FilmQueue>(EMPTY_QUEUE)
  const [capabilities, setCapabilities] = useState<FilmCapabilities | null>(null)
  const [continuity, setContinuity] = useState<ProjectContinuity | null>(null)
  const projectIdRef = useRef<string | null>(null)
  projectIdRef.current = currentProjectId

  const refresh = useCallback(async (): Promise<FilmProject | null> => {
    const projectId = projectIdRef.current
    if (!projectId) return null
    try {
      const project = await filmApi.getProject(projectId)
      if (projectIdRef.current === projectId) {
        setFilmState(project)
        setError(null)
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
  }, [])

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

  const setFilm = useCallback((next: FilmProject) => {
    setFilmState(next)
  }, [])

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
    }),
    [film, isLoading, error, refresh, setFilm, queue, capabilities, refreshCapabilities, isGenerating, findShot, continuity, continuityLevelFor, setShotContinuity],
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
