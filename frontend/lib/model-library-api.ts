// Typed client for /api/models/library — search, download, remember.

import { backendFetch } from './backend'
import type { LibraryDownloadStatus, ModelSearchResponse, ProviderTestResult } from '../types/models'

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

export interface ModelSearchParams {
  query?: string
  task?: 'all' | 'video' | 'image' | 'text'
  source?: 'all' | 'local' | 'hosted'
  onlyCompatible?: boolean
  refresh?: boolean
  limit?: number
}

export const modelLibraryApi = {
  search: (params: ModelSearchParams = {}) => {
    const query = new URLSearchParams()
    if (params.query) query.set('query', params.query)
    if (params.task && params.task !== 'all') query.set('task', params.task)
    if (params.source && params.source !== 'all') query.set('source', params.source)
    if (params.onlyCompatible) query.set('only_compatible', 'true')
    if (params.refresh) query.set('refresh', 'true')
    if (params.limit) query.set('limit', String(params.limit))
    const suffix = query.toString()
    return request<ModelSearchResponse>(`/api/models/library${suffix ? `?${suffix}` : ''}`)
  },

  startDownload: (provider: string, modelId: string) =>
    request<LibraryDownloadStatus>('/api/models/library/download', {
      method: 'POST',
      body: JSON.stringify({ provider, model_id: modelId }),
    }),

  downloadStatus: () => request<LibraryDownloadStatus>('/api/models/library/download'),

  cancelDownload: () => request<LibraryDownloadStatus>('/api/models/library/download/cancel', { method: 'POST' }),

  /** Keep a model id the user typed so it stays one click away next time. */
  remember: (provider: string, modelId: string) =>
    request<{ status: string }>('/api/models/library/remember', {
      method: 'POST',
      body: JSON.stringify({ provider, model_id: modelId }),
    }),

  /** Ask a provider whether the stored key actually works. */
  testProvider: (provider: string) =>
    request<ProviderTestResult>(`/api/models/library/providers/${encodeURIComponent(provider)}/test`, {
      method: 'POST',
    }),
}
