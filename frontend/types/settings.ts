/**
 * The app-settings contract: the exact shape `GET /api/settings` returns and
 * `POST /api/settings` accepts, plus the provider key identifiers.
 *
 * Kept beside the other API mirrors (`film.ts`, `models.ts`) rather than in the
 * React context, so anything that needs the contract — the context, and the
 * UI-only mock backend in `devtools/ui-mock` — can share one definition
 * without pulling in React.
 */

export interface InferenceSettings {
  steps: number
  useUpscaler: boolean
}

export interface FastModelSettings {
  useUpscaler: boolean
}

export type DirectorProviderSetting = 'auto' | 'gemini' | 'openrouter' | 'openai_compatible' | 'anthropic' | 'xai'

/** Backend key identifiers accepted by DELETE /api/settings/api-keys/{provider}. */
export type ClearableKeyProvider =
  | 'ltx'
  | 'fal'
  | 'gemini'
  | 'openrouter'
  | 'openai-compatible'
  | 'anthropic'
  | 'xai'
  | 'wavespeed'
  | 'replicate'

/** Settings field each provider's key is stored under (write-only from here). */
export const API_KEY_FIELDS = {
  ltx: 'ltxApiKey',
  fal: 'falApiKey',
  gemini: 'geminiApiKey',
  openrouter: 'openrouterApiKey',
  'openai-compatible': 'openaiCompatibleApiKey',
  anthropic: 'anthropicApiKey',
  xai: 'xaiApiKey',
  wavespeed: 'wavespeedApiKey',
  replicate: 'replicateApiKey',
} as const satisfies Record<ClearableKeyProvider, string>

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
  hasAnthropicApiKey: boolean
  anthropicModel: string
  hasXaiApiKey: boolean
  xaiModel: string
  geminiModel: string
  /** Where image/video generation runs; "local" keeps everything offline. */
  mediaProvider: 'local' | 'fal' | 'wavespeed' | 'replicate'
  hasWavespeedApiKey: boolean
  hasReplicateApiKey: boolean
  defaultVideoModel: string
  defaultImageModel: string
  recentModelIds: string[]
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
  hasAnthropicApiKey: false,
  anthropicModel: '',
  hasXaiApiKey: false,
  xaiModel: '',
  geminiModel: '',
  mediaProvider: 'local',
  hasWavespeedApiKey: false,
  hasReplicateApiKey: false,
  defaultVideoModel: '',
  defaultImageModel: '',
  recentModelIds: [],
  useLocalTextEncoder: false,
  fastModel: { useUpscaler: true },
  proModel: { steps: 20, useUpscaler: true },
  promptCacheSize: 1,
  promptEnhancerEnabledT2V: false,
  promptEnhancerEnabledI2V: false,
  seedLocked: false,
  lockedSeed: 42,
}
