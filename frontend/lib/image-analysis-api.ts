import { backendFetch, getBackendCredentials } from './backend'

export interface ImageCandidate {
  id: string
  path: string
  prompt: string
  score: number
  round: number
  model: string
}
export interface ImageRevision { differences: string; prompt: string }
export interface ImageAnalysis {
  id: string
  title: string
  source_path: string
  width: number
  height: number
  prompt: string
  description: string
  subjects: string
  composition: string
  colors: string
  lighting: string
  style: string
  vision_model: string
  image_model: string
  confidence: number
  candidates: ImageCandidate[]
  revisions: ImageRevision[]
  best_candidate_id: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    const data: { error?: string; detail?: string } = await response.json().catch(() => ({}))
    throw new Error(data.error || data.detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}
const enc = encodeURIComponent
export const imageAnalysisApi = {
  list: () => request<{ analyses: ImageAnalysis[] }>('/api/image-analysis').then(data => data.analyses),
  get: (id: string) => request<ImageAnalysis>(`/api/image-analysis/${enc(id)}`),
  import: (path: string) => request<ImageAnalysis>('/api/image-analysis/import', { method: 'POST', body: JSON.stringify({ path }) }),
  analyze: (id: string) => request<ImageAnalysis>(`/api/image-analysis/${enc(id)}/analyze`, { method: 'POST' }),
  editPrompt: (id: string, prompt: string) => request<ImageAnalysis>(`/api/image-analysis/${enc(id)}/prompt`, { method: 'PUT', body: JSON.stringify({ prompt }) }),
  render: (id: string, candidates = 2) => request<ImageAnalysis>(`/api/image-analysis/${enc(id)}/render`, { method: 'POST', body: JSON.stringify({ candidates, rounds: 1 }) }),
  refine: (id: string, candidates = 1) => request<ImageAnalysis>(`/api/image-analysis/${enc(id)}/refine`, { method: 'POST', body: JSON.stringify({ candidates }) }),
  remove: (id: string) => request<{ status: string }>(`/api/image-analysis/${enc(id)}`, { method: 'DELETE' }),
}
export async function imageAnalysisMediaUrl(id: string, path: string): Promise<string> {
  const { url, token } = await getBackendCredentials()
  return `${url}/api/image-analysis/${enc(id)}/media?path=${enc(path)}&token=${enc(token)}`
}
