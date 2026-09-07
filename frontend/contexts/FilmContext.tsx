import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { filmApi } from '../lib/film-api'
import { logger } from '../lib/logger'
import type { FilmCapabilities, FilmProject, FilmQueue, FilmScene, FilmShot } from '../types/film'
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
}

const FilmContext = createContext<FilmContextType | null>(null)

const EMPTY_QUEUE: FilmQueue = { active: null, pending: [] }

export function FilmProvider({ children }: { children: React.ReactNode }) {
  const { currentProjectId, currentTab } = useProjects()
  const [film, setFilmState] = useState<FilmProject | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queue, setQueue] = useState<FilmQueue>(EMPTY_QUEUE)
  const [capabilities, setCapabilities] = useState<FilmCapabilities | null>(null)
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

  const isGenerating = queue.active !== null || queue.pending.length > 0

  const value = useMemo(
    () => ({
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
    }),
    [film, isLoading, error, refresh, setFilm, queue, capabilities, refreshCapabilities, isGenerating, findShot],
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
