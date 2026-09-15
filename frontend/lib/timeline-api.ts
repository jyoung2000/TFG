// Typed client for /api/film/projects/{id}/timeline.

import { backendFetch } from './backend'
import type {
  TimelineActionName,
  TimelineActionResult,
  TimelineHistoryResult,
  TimelineView,
} from '../types/timeline'

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

const enc = encodeURIComponent
const base = (projectId: string) => `/api/film/projects/${enc(projectId)}/timeline`

export const timelineApi = {
  view: (projectId: string) => request<TimelineView>(base(projectId)),

  history: (projectId: string, limit = 50) =>
    request<TimelineHistoryResult>(`${base(projectId)}/history?limit=${limit}`),

  /** Apply one edit. A refused edit changes nothing and throws with the reason. */
  apply: (
    projectId: string,
    action: TimelineActionName,
    params: Record<string, unknown> = {},
    actor: 'user' | 'director' = 'user',
  ) =>
    request<TimelineActionResult>(`${base(projectId)}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, params, actor }),
    }),

  undo: (projectId: string) =>
    request<TimelineActionResult>(`${base(projectId)}/undo`, { method: 'POST' }),
}
