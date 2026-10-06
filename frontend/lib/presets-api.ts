import { backendFetch } from './backend'
import type { AppSettings } from '../types/settings'

export interface VideoProfileSpec {
  id: 'fast' | 'balanced'
  label: string
  model: string
  resolution: string
  duration_seconds: number
  note: string
}

export interface HardwarePresetInfo {
  id: string
  name: string
  description: string
  changes: string[]
  recommended: boolean
  applied: boolean
  video_profiles: VideoProfileSpec[]
}

export interface HardwarePresetsResponse {
  presets: HardwarePresetInfo[]
  gpu_name: string | null
  gpu_vram_gb: number | null
  applied: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.error === 'string' ? body.error : JSON.stringify(body)
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

/** Hardware presets: one click sets every default that depends on the card. */
export const presetsApi = {
  list: () => request<HardwarePresetsResponse>('/api/settings/presets'),
  apply: (id: string) => request<Partial<AppSettings>>(`/api/settings/presets/${encodeURIComponent(id)}/apply`, { method: 'POST' }),
}

/**
 * First run: apply the preset recommended for this GPU when none has been
 * applied yet. Returns the applied preset id, or '' when nothing matched.
 */
export async function applyRecommendedPreset(): Promise<string> {
  const { presets, applied } = await presetsApi.list()
  if (applied) return applied
  const recommended = presets.find(p => p.recommended)
  if (!recommended) return ''
  await presetsApi.apply(recommended.id)
  return recommended.id
}
