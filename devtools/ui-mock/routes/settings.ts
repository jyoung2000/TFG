/**
 * App settings and the runtime policy.
 *
 * Secrets follow the same rule as the real backend: a key can be written but
 * never read back — responses carry only the `has*` flags — so the masking and
 * "Remove" affordances can be exercised without a real key anywhere.
 */

import type { AppSettings, ClearableKeyProvider } from '../../../frontend/types/settings'
import { MockHttpError, type Router } from '../http'
import type { MockState, Store } from '../state'

/** Settings field each provider's key arrives under, and the flag it sets. */
const KEY_FIELDS: Record<ClearableKeyProvider, { field: string; flag: keyof AppSettings }> = {
  ltx: { field: 'ltxApiKey', flag: 'hasLtxApiKey' },
  fal: { field: 'falApiKey', flag: 'hasFalApiKey' },
  gemini: { field: 'geminiApiKey', flag: 'hasGeminiApiKey' },
  openrouter: { field: 'openrouterApiKey', flag: 'hasOpenrouterApiKey' },
  'openai-compatible': { field: 'openaiCompatibleApiKey', flag: 'hasOpenaiCompatibleApiKey' },
  anthropic: { field: 'anthropicApiKey', flag: 'hasAnthropicApiKey' },
  xai: { field: 'xaiApiKey', flag: 'hasXaiApiKey' },
  wavespeed: { field: 'wavespeedApiKey', flag: 'hasWavespeedApiKey' },
  replicate: { field: 'replicateApiKey', flag: 'hasReplicateApiKey' },
}

const FIELD_TO_PROVIDER = new Map<string, ClearableKeyProvider>(
  Object.entries(KEY_FIELDS).map(([provider, { field }]) => [field, provider as ClearableKeyProvider]),
)

function setFlag(settings: AppSettings, flag: keyof AppSettings, value: boolean): void {
  ;(settings as unknown as Record<string, unknown>)[flag] = value
}

function applySettingsPatch(state: MockState, patch: Record<string, unknown>): void {
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue

    const provider = FIELD_TO_PROVIDER.get(key)
    if (provider) {
      const secret = String(value ?? '')
      // An empty string in a normal patch is ignored: clearing is only ever
      // done through DELETE, so a stale form field cannot wipe a key.
      if (!secret.trim()) continue
      state.keys[provider] = secret
      setFlag(state.settings, KEY_FIELDS[provider].flag, true)
      if (provider === 'openrouter') state.settings.openrouterKeySource = 'settings'
      continue
    }

    if (key.startsWith('has') || key === 'openrouterKeySource') continue
    if (key in state.settings) {
      ;(state.settings as unknown as Record<string, unknown>)[key] = value
    }
  }
}

export function registerSettingsRoutes(router: Router, store: Store): void {
  router.get('/api/settings', () => store.data.settings)

  router.post('/api/settings', req =>
    store.mutate(state => {
      applySettingsPatch(state, req.body)
      return state.settings
    }),
  )

  router.delete('/api/settings/api-keys/:provider', req =>
    store.mutate(state => {
      const provider = req.params.provider as ClearableKeyProvider
      const entry = KEY_FIELDS[provider]
      if (!entry) throw new MockHttpError(404, `Unknown provider: ${req.params.provider}`)
      state.keys[provider] = ''
      setFlag(state.settings, entry.flag, false)
      if (provider === 'openrouter') state.settings.openrouterKeySource = 'none'
      return { status: 'ok' }
    }),
  )

  // A GPU is present in UI-only mode, so the app is not forced onto the cloud
  // API and every local-generation surface stays reachable.
  router.get('/api/runtime-policy', () => ({ force_api_generations: false }))
}
