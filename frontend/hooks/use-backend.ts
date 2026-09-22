import { useState, useEffect, useCallback } from 'react'
import { backendFetch, resetBackendCredentials } from '../lib/backend'
import { logger } from '../lib/logger'

interface BackendStatus {
  connected: boolean
  modelsLoaded: boolean
  gpuInfo: {
    name: string
    vram: number
    vramUsed: number
  } | null
}

interface ModelStatus {
  id: string
  name: string
  size: number
  downloaded: boolean
  downloadProgress: number
}

export type BackendProcessStatus = 'alive' | 'restarting' | 'dead'

interface BackendHealthStatusPayload {
  status: BackendProcessStatus
  exitCode?: number | null
}

interface UseBackendReturn {
  status: BackendStatus
  models: ModelStatus[]
  processStatus: BackendProcessStatus | null
  isLoading: boolean
  error: string | null
  checkHealth: () => Promise<boolean>
  downloadModel: (modelId: string) => Promise<void>
}

function toBackendHealthStatus(value: unknown): BackendHealthStatusPayload | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as { status?: unknown; exitCode?: unknown }
  if (record.status !== 'alive' && record.status !== 'restarting' && record.status !== 'dead') {
    return null
  }

  return {
    status: record.status,
    exitCode: typeof record.exitCode === 'number' || record.exitCode === null ? record.exitCode : undefined,
  }
}

export function useBackend(): UseBackendReturn {
  const [status, setStatus] = useState<BackendStatus>({
    connected: false,
    modelsLoaded: false,
    gpuInfo: null,
  })
  const [models, setModels] = useState<ModelStatus[]>([])
  const [processStatus, setProcessStatus] = useState<BackendProcessStatus | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const checkHealth = useCallback(async (): Promise<boolean> => {
    try {
      logger.info('Checking backend health...')
      const response = await backendFetch('/health')

      if (response.ok) {
        const data = await response.json()
        logger.info(`Backend health: ${JSON.stringify(data)}`)

        setStatus({
          connected: true,
          modelsLoaded: data.models_loaded,
          gpuInfo: data.gpu_info,
        })
        setError(null)
        return true
      }
      logger.warn(`Backend health check failed with status: ${response.status}`)
      return false
    } catch (err) {
      logger.error(`Backend health check error: ${err}`)
      setStatus(prev => ({ ...prev, connected: false }))
      return false
    }
  }, [])

  const fetchModels = useCallback(async () => {
    try {
      const response = await backendFetch('/api/models')

      if (response.ok) {
        const data = await response.json()
        setModels(data.models)
      }
    } catch (err) {
      logger.error(`Failed to fetch models: ${err}`)
    }
  }, [])

  const downloadModel = useCallback(async (_modelId: string) => {
    try {
      // The backend exposes a single global download pipeline:
      //   POST /api/models/download            -> start (409 if already running)
      //   GET  /api/models/download/progress   -> poll status/percentage
      // There is no per-model endpoint and no /ws/download socket.
      const startResponse = await backendFetch('/api/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skipTextEncoder: false }),
      })

      if (!startResponse.ok && startResponse.status !== 409) {
        const detail = await startResponse.json().catch(() => null)
        throw new Error(
          typeof detail?.message === 'string' && detail.message
            ? detail.message
            : `Failed to start download (HTTP ${startResponse.status})`
        )
      }

      // Poll progress until the session leaves the "downloading" state.
      const poll = async () => {
        const response = await backendFetch('/api/models/download/progress')
        if (!response.ok) {
          return null
        }
        const progress = (await response.json()) as {
          status?: string
          totalProgress?: number
          error?: string | null
        }
        if (progress.status === 'downloading' && typeof progress.totalProgress === 'number') {
          setModels(prev =>
            prev.map(m => ({ ...m, downloadProgress: progress.totalProgress ?? 0 }))
          )
          return true
        }
        if (progress.status === 'complete') {
          setModels(prev =>
            prev.map(m => ({ ...m, downloaded: true, downloadProgress: 100 }))
          )
          await fetchModels()
          return false
        }
        if (progress.status === 'error') {
          throw new Error(progress.error || 'Download failed')
        }
        return false
      }

      // 1s poll interval; stop once the download is no longer in flight.
      for (;;) {
        // eslint-disable-next-line no-await-in-loop
        const keepPolling = await poll()
        if (!keepPolling) {
          break
        }
        // eslint-disable-next-line no-await-in-loop
        await new Promise(resolve => setTimeout(resolve, 1000))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed')
    }
  }, [fetchModels])

  const handleBackendStatus = useCallback(async (payload: BackendHealthStatusPayload) => {
    setProcessStatus(payload.status)

    if (payload.status === 'alive') {
      // Reset cached credentials so the new port/token are fetched
      resetBackendCredentials()
      const healthy = await checkHealth()
      if (healthy) {
        await fetchModels()
      } else {
        setError('Failed to connect to backend')
      }
      setIsLoading(false)
      return
    }

    if (payload.status === 'restarting') {
      return
    }

    setStatus((prev) => ({ ...prev, connected: false }))
    setError('The backend process crashed and could not be restarted')
    setIsLoading(false)
  }, [checkHealth, fetchModels])

  useEffect(() => {
    let cancelled = false

    const applyStatus = async (value: unknown) => {
      const payload = toBackendHealthStatus(value)
      if (!payload || cancelled) {
        return
      }
      await handleBackendStatus(payload)
    }

    const unsubscribe = window.electronAPI.onBackendHealthStatus((data: BackendHealthStatusPayload) => {
      void applyStatus(data)
    })

    const init = async () => {
      try {
        const snapshot = await window.electronAPI.getBackendHealthStatus()
        await applyStatus(snapshot)
      } catch (err) {
        logger.error(`Failed to load backend health status snapshot: ${err}`)
      }
    }

    void init()

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [handleBackendStatus])

  return {
    status,
    models,
    processStatus,
    isLoading,
    error,
    checkHealth,
    downloadModel,
  }
}
