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
      const target = state.settings as unknown as Record<string, unknown>
      const current = target[key]
      // Nested sections (vision, learning, model settings) are patched, not replaced.
      if (current && typeof current === 'object' && !Array.isArray(current) && value && typeof value === 'object' && !Array.isArray(value)) {
        target[key] = { ...(current as Record<string, unknown>), ...(value as Record<string, unknown>) }
      } else {
        target[key] = value
      }
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

  const PRESET = {
    id: 'rtx-4070-12gb',
    name: 'RTX 4070 · 12 GB',
    description: 'Everything local and sized for 12 GB of VRAM: distilled LTX-2 for video, Z-Image for stills, the small vision stack, no VLM by default.',
    changes: [
      'Video: LTX-2 22B distilled — Fast profile (540p · 6 s), Balanced available (720p · 6–8 s)',
      'Image: Z-Image at 8 steps',
      'Vision: Florence-2-large captions, CLIP ViT-L/14 tags, Depth-Anything-V2-small, DINOv2-small',
      'VLM off by default; keep_alive 0 so it never holds VRAM',
      'Local text encoder on, media provider local, VRAM budget 12 GB',
    ],
    video_profiles: [
      { id: 'fast', label: 'Fast', model: 'ltx2_22B_distilled', resolution: '540p', duration_seconds: 6, note: '540p · 6 s · 8 steps' },
      { id: 'balanced', label: 'Balanced', model: 'ltx2_22B_distilled', resolution: '720p', duration_seconds: 8, note: '720p · 6–8 s' },
    ],
  }
  router.get('/api/settings/tiers', () => {
    const s = store.data.settings
    const keyFor: Record<string, boolean> = { fal: s.hasFalApiKey, wavespeed: s.hasWavespeedApiKey, replicate: s.hasReplicateApiKey }
    const out: Record<string, { provider: string; model: string; skip_reason: string }[]> = {}
    for (const task of ['t2i', 'i2i', 't2v', 'i2v', 'edit']) {
      const order = s.mediaTiers[task]?.length ? s.mediaTiers[task] : [s.mediaProvider || 'local']
      out[task] = order.map(provider => {
        if (provider === 'local') return { provider, model: 'local', skip_reason: task === 'i2i' || task === 'edit' ? `local engine cannot do ${task} yet` : '' }
        if (!keyFor[provider]) return { provider, model: '', skip_reason: `${provider.toUpperCase()}_KEY_MISSING` }
        const model = task.endsWith('2i') || task === 'edit' ? s.defaultImageModel : s.defaultVideoModel
        return model ? { provider, model, skip_reason: '' } : { provider, model: '', skip_reason: `no ${provider} model id for ${task}` }
      })
    }
    return out
  })

  router.get('/api/settings/presets', () => ({
    presets: [{ ...PRESET, recommended: true, applied: store.data.settings.hardwarePreset === PRESET.id }],
    gpu_name: 'NVIDIA GeForce RTX 4070',
    gpu_vram_gb: 12,
    applied: store.data.settings.hardwarePreset,
  }))
  router.post('/api/settings/presets/:id/apply', req =>
    store.mutate(state => {
      if (req.params.id !== PRESET.id) throw new MockHttpError(404, `Unknown hardware preset: ${req.params.id}`)
      applySettingsPatch(state, {
        hardwarePreset: PRESET.id, gpuVramBudgetGb: 12, defaultVideoModel: 'ltx2_22B_distilled', defaultImageModel: 'z_image', videoProfile: 'fast', imageSteps: 8, useLocalTextEncoder: true, mediaProvider: 'local',
        vision: { ...state.settings.vision, florenceModel: 'florence-2-large', clipModel: 'openai/clip-vit-large-patch14', depthModel: 'depth-anything-v2-small', dinoModel: 'dinov2-small', vlmProvider: 'off', vlmKeepAlive: '0' },
      })
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
