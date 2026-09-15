// Typed client for /api/video-analysis.

import { backendFetch, getBackendCredentials } from './backend'
import { mediaResolver } from './media-resolver'
import type { FilmProject } from '../types/film'
import type { AnalysisDepth, VideoAnalysis } from '../types/video-analysis'

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

export interface ImportVideoOptions {
  path: string
  title?: string
  depth?: AnalysisDepth
  sensitivity?: number
  min_shot_seconds?: number
  max_shots?: number
  detect_fades?: boolean
  analyze_audio?: boolean
  analyze_text?: boolean
}

export const videoAnalysisApi = {
  list: () => request<{ analyses: VideoAnalysis[] }>('/api/video-analysis').then(r => r.analyses),

  get: (id: string) => request<VideoAnalysis>(`/api/video-analysis/${enc(id)}`),

  importVideo: (options: ImportVideoOptions) =>
    request<VideoAnalysis>('/api/video-analysis/import', { method: 'POST', body: JSON.stringify(options) }),

  remove: (id: string) => request<{ status: string }>(`/api/video-analysis/${enc(id)}`, { method: 'DELETE' }),

  detect: (id: string) => request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/detect`, { method: 'POST' }),

  analyze: (id: string, offlineOnly = false) =>
    request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ offline_only: offlineOnly }),
    }),

  cancel: (id: string) => request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/cancel`, { method: 'POST' }),

  split: (id: string, shotId: string, at: number) =>
    request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/shots/${enc(shotId)}/split`, {
      method: 'POST',
      body: JSON.stringify({ at }),
    }),

  merge: (id: string, shotId: string) =>
    request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/shots/${enc(shotId)}/merge`, { method: 'POST' }),

  moveBoundary: (id: string, shotId: string, edges: { start?: number; end?: number }) =>
    request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/shots/${enc(shotId)}/boundary`, {
      method: 'PUT',
      body: JSON.stringify(edges),
    }),

  editPrompts: (id: string, shotId: string, prompts: Record<string, string>) =>
    request<VideoAnalysis>(`/api/video-analysis/${enc(id)}/shots/${enc(shotId)}/prompts`, {
      method: 'PUT',
      body: JSON.stringify(prompts),
    }),

  reconstruct: (id: string, options: { project_id?: string; name?: string } = {}) =>
    request<FilmProject>(`/api/video-analysis/${enc(id)}/reconstruct`, {
      method: 'POST',
      body: JSON.stringify(options),
    }),
}

/** URL for one extracted still, authenticated the same way film media is. */
export async function analysisFrameUrl(analysisId: string, framePath: string): Promise<string> {
  // The standalone build has no origin to serve from, so frames resolve to a
  // data URL exactly as film captures do.
  const standalone = mediaResolver()
  if (standalone) return standalone.media(analysisId, framePath)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/video-analysis/${enc(analysisId)}/frame?path=${enc(framePath)}&token=${enc(token)}`
}
