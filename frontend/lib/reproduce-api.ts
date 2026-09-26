import { backendFetch, getBackendCredentials } from './backend'
import { mediaResolver } from './media-resolver'
import type { PromptStyle, ShotSpec, SpecCompileResult, PromptHints } from '../types/shotspec'
import type { ReproduceBudget, ReproduceJob } from '../types/reproduce'

const enc = encodeURIComponent

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.error === 'string' ? body.error : typeof body?.message === 'string' ? body.message : JSON.stringify(body)
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

export interface FixPayload {
  exposure?: number
  contrast?: number
  saturation?: number
  hue?: number
  black_point?: number
  white_point?: number
  gamma?: number
  temperature?: number
  mask_png_base64?: string
  patch_from_reference?: boolean
  inpaint_prompt?: string
}

export const reproduceApi = {
  list: () => request<{ jobs: ReproduceJob[] }>('/api/reproduce').then(r => r.jobs),
  get: (id: string) => request<ReproduceJob>(`/api/reproduce/${enc(id)}`),
  import: (path: string) => request<ReproduceJob>('/api/reproduce/import', { method: 'POST', body: JSON.stringify({ path }) }),
  remove: (id: string) => request<{ status: string }>(`/api/reproduce/${enc(id)}`, { method: 'DELETE' }),
  analyze: (id: string) => request<ReproduceJob>(`/api/reproduce/${enc(id)}/analyze`, { method: 'POST' }),
  updateSpec: (id: string, sections: Partial<ShotSpec>, locks?: Record<string, boolean>) =>
    request<ReproduceJob>(`/api/reproduce/${enc(id)}/spec`, { method: 'PUT', body: JSON.stringify({ sections, locks }) }),
  setPrompt: (id: string, prompt: string, target?: string, style?: PromptStyle | null) =>
    request<ReproduceJob>(`/api/reproduce/${enc(id)}/prompt`, { method: 'PUT', body: JSON.stringify({ prompt, target, style }) }),
  start: (id: string, budget: ReproduceBudget, seed: number | null, useVlm: boolean, loras: { name: string; multiplier: number }[] = []) =>
    request<ReproduceJob>(`/api/reproduce/${enc(id)}/start`, { method: 'POST', body: JSON.stringify({ budget, seed, use_vlm: useVlm, loras }) }),
  cancel: (id: string) => request<ReproduceJob>(`/api/reproduce/${enc(id)}/cancel`, { method: 'POST' }),
  pin: (id: string, candidateId: string) => request<ReproduceJob>(`/api/reproduce/${enc(id)}/pin/${enc(candidateId || 'source')}`, { method: 'POST' }),
  pick: (id: string, candidateId: string) => request<ReproduceJob>(`/api/reproduce/${enc(id)}/pick/${enc(candidateId)}`, { method: 'POST' }),
  fix: (id: string, candidateId: string, payload: FixPayload) =>
    request<ReproduceJob>(`/api/reproduce/${enc(id)}/candidates/${enc(candidateId)}/fix`, { method: 'POST', body: JSON.stringify(payload) }),
  compileAll: (spec: ShotSpec, targets: string[], styles: PromptStyle[]) =>
    request<{ results: Record<string, SpecCompileResult>; hints: PromptHints | null }>('/api/prompts/compile-spec/all', {
      method: 'POST',
      body: JSON.stringify({ spec, targets, styles }),
    }),
}

export async function reproduceMediaUrl(id: string, path: string): Promise<string> {
  const standalone = mediaResolver()
  if (standalone) return standalone.output(`${id}/${path}`)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/reproduce/${enc(id)}/media?path=${enc(path)}&token=${enc(token)}`
}
