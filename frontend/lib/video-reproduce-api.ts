import { backendFetch, getBackendCredentials } from './backend'
import { mediaResolver } from './media-resolver'
import type { VideoReproduceJob, VideoReproduceRequest } from '../types/video-reproduce'
import type { VideoRecreationResponse } from './video-analysis-api'

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

export const videoReproduceApi = {
  get: (analysisId: string) => request<VideoReproduceJob>(`/api/video-reproduce/${enc(analysisId)}`),
  start: (analysisId: string, req: VideoReproduceRequest) =>
    request<VideoRecreationResponse>(`/api/video-reproduce/${enc(analysisId)}/start`, { method: 'POST', body: JSON.stringify(req) }),
  cancel: (analysisId: string) => request<VideoReproduceJob>(`/api/video-reproduce/${enc(analysisId)}/cancel`, { method: 'POST' }),
  pick: (analysisId: string, shotId: string, candidateId: string) =>
    request<VideoReproduceJob>(`/api/video-reproduce/${enc(analysisId)}/shots/${enc(shotId)}/pick/${enc(candidateId)}`, { method: 'POST' }),
  redo: (analysisId: string, shotId: string) =>
    request<VideoReproduceJob>(`/api/video-reproduce/${enc(analysisId)}/shots/${enc(shotId)}/redo`, { method: 'POST' }),
  stitch: (analysisId: string) => request<VideoReproduceJob>(`/api/video-reproduce/${enc(analysisId)}/stitch`, { method: 'POST' }),
}

/** Authenticated URL for a candidate clip, a frame thumbnail or the stitched result. */
export async function videoReproduceMediaUrl(analysisId: string, path: string): Promise<string> {
  const standalone = mediaResolver()
  if (standalone) return standalone.output(path)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/video-reproduce/${enc(analysisId)}/media?path=${enc(path)}&token=${enc(token)}`
}
