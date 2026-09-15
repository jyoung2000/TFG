// Typed client for /api/knowledge.

import { backendFetch } from './backend'
import type {
  KnowledgeEvent,
  KnowledgeExport,
  KnowledgeSummary,
  LearningSettings,
  ModelProfile,
  RecommendResponse,
} from '../types/knowledge'

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

export interface FeedbackInput {
  model: string
  provider?: string
  project_id?: string
  shot_id?: string
  /** 1..5, or omitted for a note without a score. */
  rating?: number
  note?: string
}

export const knowledgeApi = {
  summary: () => request<KnowledgeSummary>('/api/knowledge'),

  profiles: () => request<{ models: ModelProfile[] }>('/api/knowledge/models').then(r => r.models),

  events: (options: { project_id?: string; limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (options.project_id) params.set('project_id', options.project_id)
    if (options.limit) params.set('limit', String(options.limit))
    const query = params.toString()
    return request<KnowledgeEvent[]>(`/api/knowledge/events${query ? `?${query}` : ''}`)
  },

  updateLearning: (settings: LearningSettings) =>
    request<LearningSettings>('/api/knowledge/settings', { method: 'PUT', body: JSON.stringify(settings) }),

  /** Resolves to 'declined' when the user has feedback learning switched off. */
  feedback: (input: FeedbackInput) =>
    request<{ status: string }>('/api/knowledge/feedback', { method: 'POST', body: JSON.stringify(input) }),

  recommend: (task: string, candidates: string[]) =>
    request<RecommendResponse>('/api/knowledge/recommend', {
      method: 'POST',
      body: JSON.stringify({ task, candidates }),
    }),

  export: () => request<KnowledgeExport>('/api/knowledge/export'),

  import: (payload: KnowledgeExport, replace = false) =>
    request<{ status: string }>('/api/knowledge/import', {
      method: 'POST',
      body: JSON.stringify({ payload, replace }),
    }),

  /** Empty model and project_id means "forget everything". */
  reset: (options: { model?: string; project_id?: string } = {}) =>
    request<{ status: string }>('/api/knowledge/reset', {
      method: 'POST',
      body: JSON.stringify({ model: options.model ?? '', project_id: options.project_id ?? '' }),
    }),
}
