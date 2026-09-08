import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { backendFetch, resetBackendCredentials } from '../lib/backend'

export interface InferenceSettings {
  steps: number
  useUpscaler: boolean
}

export interface FastModelSettings {
  useUpscaler: boolean
}

export type DirectorProviderSetting = 'auto' | 'gemini' | 'openrouter' | 'openai_compatible'

/** Backend key identifiers accepted by DELETE /api/settings/api-keys/{provider}. */
export type ClearableKeyProvider = 'ltx' | 'fal' | 'gemini' | 'openrouter' | 'openai-compatible'

/** Preferred OpenRouter model per AI Director role ('' = defaultModel). */
export interface OpenRouterRoleModels {
  defaultModel: string
  script: string
  storyboard: string
  director: string
  continuity: string
  prompt_refinement: string
}

export interface AppSettings {
  useTorchCompile: boolean
  loadOnStartup: boolean
  hasLtxApiKey: boolean
  userPrefersLtxApiVideoGenerations: boolean
  hasFalApiKey: boolean
  hasGeminiApiKey: boolean
  hasOpenrouterApiKey: boolean
  openrouterKeySource: 'settings' | 'env' | 'none'
  directorProvider: DirectorProviderSetting
  openrouterModels: OpenRouterRoleModels
  /** OpenAI-compatible endpoint (LM Studio, vLLM, Ollama's OpenAI shim…): /v1 base URL + model id. */
  openaiCompatibleBaseUrl: string
  openaiCompatibleModel: string
  hasOpenaiCompatibleApiKey: boolean
  useLocalTextEncoder: boolean
  fastModel: FastModelSettings
  proModel: InferenceSettings
  promptCacheSize: number
  promptEnhancerEnabledT2V: boolean
  promptEnhancerEnabledI2V: boolean
  seedLocked: boolean
  lockedSeed: number
}

export const DEFAULT_OPENROUTER_ROLE_MODELS: OpenRouterRoleModels = {
  defaultModel: 'openai/gpt-4o-mini',
  script: '',
  storyboard: '',
  director: '',
  continuity: '',
  prompt_refinement: '',
}

export const DEFAULT_APP_SETTINGS: AppSettings = {
  useTorchCompile: false,
  loadOnStartup: true,
  hasLtxApiKey: false,
  userPrefersLtxApiVideoGenerations: false,
  hasFalApiKey: false,
  hasGeminiApiKey: false,
  hasOpenrouterApiKey: false,
  openrouterKeySource: 'none',
  directorProvider: 'auto',
  openrouterModels: DEFAULT_OPENROUTER_ROLE_MODELS,
  openaiCompatibleBaseUrl: '',
  openaiCompatibleModel: '',
  hasOpenaiCompatibleApiKey: false,
  useLocalTextEncoder: false,
  fastModel: { useUpscaler: true },
  proModel: { steps: 20, useUpscaler: true },
  promptCacheSize: 1,
  promptEnhancerEnabledT2V: false,
  promptEnhancerEnabledI2V: false,
  seedLocked: false,
  lockedSeed: 42,
}

type BackendProcessStatus = 'alive' | 'restarting' | 'dead'

interface AppSettingsContextValue {
  settings: AppSettings
  isLoaded: boolean
  runtimePolicyLoaded: boolean
  updateSettings: (patch: Partial<AppSettings> | ((prev: AppSettings) => AppSettings)) => void
  refreshSettings: () => Promise<void>
  saveLtxApiKey: (value: string) => Promise<void>
  saveFalApiKey: (value: string) => Promise<void>
  saveGeminiApiKey: (value: string) => Promise<void>
  saveOpenrouterApiKey: (value: string) => Promise<void>
  saveOpenaiCompatibleApiKey: (value: string) => Promise<void>
  /** Remove a stored secret (e.g. after the provider rejected it). */
  clearApiKey: (provider: ClearableKeyProvider) => Promise<void>
  /** True when the selected AI Director provider is usable (key present, or endpoint + model set). */
  hasDirectorProvider: boolean
  forceApiGenerations: boolean
  shouldVideoGenerateWithLtxApi: boolean
}

const AppSettingsContext = createContext<AppSettingsContextValue | null>(null)

function toBackendProcessStatus(value: unknown): BackendProcessStatus | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as { status?: unknown }
  if (record.status === 'alive' || record.status === 'restarting' || record.status === 'dead') {
    return record.status
  }
  return null
}

function normalizeAppSettings(data: Partial<AppSettings>): AppSettings {
  return {
    useTorchCompile: data.useTorchCompile ?? DEFAULT_APP_SETTINGS.useTorchCompile,
    loadOnStartup: data.loadOnStartup ?? DEFAULT_APP_SETTINGS.loadOnStartup,
    hasLtxApiKey: data.hasLtxApiKey ?? DEFAULT_APP_SETTINGS.hasLtxApiKey,
    userPrefersLtxApiVideoGenerations: data.userPrefersLtxApiVideoGenerations ?? DEFAULT_APP_SETTINGS.userPrefersLtxApiVideoGenerations,
    hasFalApiKey: data.hasFalApiKey ?? DEFAULT_APP_SETTINGS.hasFalApiKey,
    hasGeminiApiKey: data.hasGeminiApiKey ?? DEFAULT_APP_SETTINGS.hasGeminiApiKey,
    hasOpenrouterApiKey: data.hasOpenrouterApiKey ?? DEFAULT_APP_SETTINGS.hasOpenrouterApiKey,
    openrouterKeySource: data.openrouterKeySource ?? DEFAULT_APP_SETTINGS.openrouterKeySource,
    directorProvider: data.directorProvider ?? DEFAULT_APP_SETTINGS.directorProvider,
    openrouterModels: { ...DEFAULT_OPENROUTER_ROLE_MODELS, ...(data.openrouterModels ?? {}) },
    openaiCompatibleBaseUrl: data.openaiCompatibleBaseUrl ?? DEFAULT_APP_SETTINGS.openaiCompatibleBaseUrl,
    openaiCompatibleModel: data.openaiCompatibleModel ?? DEFAULT_APP_SETTINGS.openaiCompatibleModel,
    hasOpenaiCompatibleApiKey: data.hasOpenaiCompatibleApiKey ?? DEFAULT_APP_SETTINGS.hasOpenaiCompatibleApiKey,
    useLocalTextEncoder: data.useLocalTextEncoder ?? DEFAULT_APP_SETTINGS.useLocalTextEncoder,
    fastModel: data.fastModel ?? DEFAULT_APP_SETTINGS.fastModel,
    proModel: data.proModel ?? DEFAULT_APP_SETTINGS.proModel,
    promptCacheSize: data.promptCacheSize ?? DEFAULT_APP_SETTINGS.promptCacheSize,
    promptEnhancerEnabledT2V: data.promptEnhancerEnabledT2V ?? DEFAULT_APP_SETTINGS.promptEnhancerEnabledT2V,
    promptEnhancerEnabledI2V: data.promptEnhancerEnabledI2V ?? DEFAULT_APP_SETTINGS.promptEnhancerEnabledI2V,
    seedLocked: data.seedLocked ?? DEFAULT_APP_SETTINGS.seedLocked,
    lockedSeed: data.lockedSeed ?? DEFAULT_APP_SETTINGS.lockedSeed,
  }
}

export function AppSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_APP_SETTINGS)
  const [isLoaded, setIsLoaded] = useState(false)
  const [runtimePolicyLoaded, setRuntimePolicyLoaded] = useState(false)
  const [forceApiGenerations, setForceApiGenerations] = useState(true)
  const [backendProcessStatus, setBackendProcessStatus] = useState<BackendProcessStatus | null>(null)

  useEffect(() => {
    if (backendProcessStatus !== 'alive') return

    let cancelled = false
    setRuntimePolicyLoaded(false)

    const fetchRuntimePolicy = async () => {
      try {
        const response = await backendFetch('/api/runtime-policy')
        if (!response.ok) {
          throw new Error(`Runtime policy fetch failed with status ${response.status}`)
        }

        const payload = (await response.json()) as { force_api_generations?: unknown }
        if (typeof payload.force_api_generations !== 'boolean') {
          throw new Error('Runtime policy response missing force_api_generations boolean')
        }

        if (!cancelled) {
          setForceApiGenerations(payload.force_api_generations)
        }
      } catch {
        if (!cancelled) {
          // Fail closed until policy can be read.
          setForceApiGenerations(true)
        }
      } finally {
        if (!cancelled) {
          setRuntimePolicyLoaded(true)
        }
      }
    }

    void fetchRuntimePolicy()

    return () => {
      cancelled = true
    }
  }, [backendProcessStatus])

  useEffect(() => {
    let cancelled = false

    const applyStatus = (value: unknown) => {
      const nextStatus = toBackendProcessStatus(value)
      if (!nextStatus || cancelled) {
        return
      }
      if (nextStatus === 'alive') {
        resetBackendCredentials()
      }
      setBackendProcessStatus(nextStatus)
    }

    const unsubscribe = window.electronAPI.onBackendHealthStatus((data) => {
      applyStatus(data)
    })

    void window.electronAPI.getBackendHealthStatus()
      .then((snapshot) => {
        applyStatus(snapshot)
      })
      .catch(() => {
        // Snapshot is optional at startup; subscription continues to listen for pushes.
      })

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [])

  const refreshSettings = useCallback(async () => {
    const response = await backendFetch('/api/settings')
    if (!response.ok) {
      throw new Error(`Settings fetch failed with status ${response.status}`)
    }
    const data = await response.json()
    setSettings(normalizeAppSettings(data))
    setIsLoaded(true)
  }, [])

  useEffect(() => {
    if (isLoaded || backendProcessStatus !== 'alive') return

    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const fetchSettings = async () => {
      try {
        await refreshSettings()
        if (cancelled) return
      } catch {
        if (!cancelled) {
          retryTimer = setTimeout(fetchSettings, 1000)
        }
      }
    }

    fetchSettings()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [backendProcessStatus, isLoaded, refreshSettings])

  useEffect(() => {
    if (!isLoaded || backendProcessStatus !== 'alive') return
    const syncTimer = setTimeout(async () => {
      try {
        // Derived/read-only fields never go back to the backend.
        const {
          hasLtxApiKey: _a,
          hasFalApiKey: _b,
          hasGeminiApiKey: _c,
          hasOpenrouterApiKey: _d,
          openrouterKeySource: _e,
          hasOpenaiCompatibleApiKey: _f,
          ...syncPayload
        } = settings
        await backendFetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(syncPayload),
        })
      } catch {
        // Best-effort settings sync.
      }
    }, 150)
    return () => clearTimeout(syncTimer)
  }, [backendProcessStatus, isLoaded, settings])

  const updateSettings = useCallback((patch: Partial<AppSettings> | ((prev: AppSettings) => AppSettings)) => {
    if (typeof patch === 'function') {
      setSettings((prev) => patch(prev))
      return
    }
    setSettings((prev) => ({ ...prev, ...patch }))
  }, [])

  const saveLtxApiKey = useCallback(async (value: string) => {
    const response = await backendFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ltxApiKey: value }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || 'Failed to save LTX API key.')
    }
    await refreshSettings()
  }, [refreshSettings])

  const saveGeminiApiKey = useCallback(async (value: string) => {
    const response = await backendFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ geminiApiKey: value }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || 'Failed to save Gemini API key.')
    }
    await refreshSettings()
  }, [refreshSettings])

  const saveFalApiKey = useCallback(async (value: string) => {
    const response = await backendFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ falApiKey: value }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || 'Failed to save FAL API key.')
    }
    await refreshSettings()
  }, [refreshSettings])

  const saveOpenrouterApiKey = useCallback(async (value: string) => {
    const response = await backendFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ openrouterApiKey: value }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || 'Failed to save OpenRouter API key.')
    }
    await refreshSettings()
  }, [refreshSettings])

  const saveOpenaiCompatibleApiKey = useCallback(async (value: string) => {
    const response = await backendFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ openaiCompatibleApiKey: value }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || 'Failed to save the endpoint API key.')
    }
    await refreshSettings()
  }, [refreshSettings])

  const clearApiKey = useCallback(async (provider: ClearableKeyProvider) => {
    const response = await backendFetch(`/api/settings/api-keys/${provider}`, { method: 'DELETE' })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(detail || `Failed to clear ${provider} API key.`)
    }
    await refreshSettings()
  }, [refreshSettings])

  const shouldVideoGenerateWithLtxApi =
    forceApiGenerations || (settings.userPrefersLtxApiVideoGenerations && settings.hasLtxApiKey)

  const hasOpenaiCompatible =
    settings.openaiCompatibleBaseUrl.trim() !== '' && settings.openaiCompatibleModel.trim() !== ''
  const hasDirectorProvider =
    settings.directorProvider === 'openrouter'
      ? settings.hasOpenrouterApiKey
      : settings.directorProvider === 'gemini'
        ? settings.hasGeminiApiKey
        : settings.directorProvider === 'openai_compatible'
          ? hasOpenaiCompatible
          : settings.hasOpenrouterApiKey || settings.hasGeminiApiKey || hasOpenaiCompatible

  const contextValue = useMemo<AppSettingsContextValue>(
    () => ({
      settings,
      isLoaded,
      runtimePolicyLoaded,
      updateSettings,
      refreshSettings,
      saveLtxApiKey,
      saveFalApiKey,
      saveGeminiApiKey,
      saveOpenrouterApiKey,
      saveOpenaiCompatibleApiKey,
      clearApiKey,
      hasDirectorProvider,
      forceApiGenerations,
      shouldVideoGenerateWithLtxApi,
    }),
    [
      clearApiKey,
      forceApiGenerations,
      hasDirectorProvider,
      isLoaded,
      refreshSettings,
      runtimePolicyLoaded,
      saveFalApiKey,
      saveGeminiApiKey,
      saveLtxApiKey,
      saveOpenrouterApiKey,
      saveOpenaiCompatibleApiKey,
      settings,
      shouldVideoGenerateWithLtxApi,
      updateSettings,
    ],
  )

  return <AppSettingsContext.Provider value={contextValue}>{children}</AppSettingsContext.Provider>
}

export function useAppSettings() {
  const context = useContext(AppSettingsContext)
  if (!context) {
    throw new Error('useAppSettings must be used within AppSettingsProvider')
  }
  return context
}
