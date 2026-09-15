// Typed client for /api/prompts.

import { backendFetch } from './backend'
import type { CompilePromptResponse, PromptTarget, ShotBrief } from '../types/prompts'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) {
    let detail = ''
    try {
      const body = (await response.json()) as { error?: string; message?: string }
      detail = body?.error || body?.message || ''
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

/** Exactly one source, matching the backend's own rule. */
export type CompileSource =
  | { brief: ShotBrief }
  | { project_id: string; scene_id?: string; shot_id: string }
  | { analysis_id: string; analysis_shot_id: string }

export const promptsApi = {
  targets: () => request<{ targets: PromptTarget[] }>('/api/prompts/targets').then(r => r.targets),

  compile: (models: string[], source: CompileSource) =>
    request<CompilePromptResponse>('/api/prompts/compile', {
      method: 'POST',
      body: JSON.stringify({ models, ...source }),
    }),
}
