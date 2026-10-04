// Typed client for /api/model-manager (+ the multi-angle status route).

import { backendFetch } from './backend'

export type StorageAreaId = 'checkpoints' | 'models' | 'loras'

export interface InstalledModel {
  id: string
  name: string
  kind: 'wangp' | 'component' | 'folder' | 'lora' | 'lora-file'
  area: StorageAreaId
  size_bytes: number
  shared_bytes: number
  files: string[]
  note: string
}

export interface StorageArea {
  id: StorageAreaId
  label: string
  path: string
  size_bytes: number
  free_bytes: number
  moved_to: string
}

export interface MoveStatus {
  area: string
  destination: string
  copied_bytes: number
  total_bytes: number
  running: boolean
  error: string
}

export interface InstalledInventory {
  models: InstalledModel[]
  total_bytes: number
  areas: StorageArea[]
  move: MoveStatus
}

export interface HubModel {
  repo_id: string
  downloads: number
  likes: number
  pipeline_tag: string
  license: string
  last_modified: string
}

export interface HubFile {
  path: string
  size_bytes: number
}

export interface DownloadRequest {
  url?: string
  repo_id?: string
  path?: string
  destination: StorageAreaId
}

export interface AngleChoice {
  id: string
  label: string
  installed: boolean
}

export interface AngleStatus {
  characters: string
  objects: string
  choices: AngleChoice[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) {
    let detail = ''
    try {
      const body = (await response.json()) as { error?: string; message?: string; detail?: string }
      detail = body?.error || body?.message || (typeof body?.detail === 'string' ? body.detail : '') || ''
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

const enc = encodeURIComponent

export const modelManagerApi = {
  installed: () => request<InstalledInventory>('/api/model-manager/installed'),

  uninstall: (id: string) =>
    request<InstalledInventory>(`/api/model-manager/installed/${enc(id)}`, { method: 'DELETE' }),

  moveStorage: (area: StorageAreaId, destination: string) =>
    request<MoveStatus>('/api/model-manager/storage/move', {
      method: 'POST',
      body: JSON.stringify({ area, destination }),
    }),

  search: (q: string, limit = 20) =>
    request<HubModel[]>(`/api/model-manager/search?q=${enc(q)}&limit=${limit}`),

  files: (repo: string) => request<HubFile[]>(`/api/model-manager/files?repo=${enc(repo)}`),

  download: (body: DownloadRequest) =>
    request<{ job_id: string }>('/api/model-manager/download', { method: 'POST', body: JSON.stringify(body) }),

  cancelDownload: (jobId: string) =>
    request<unknown>(`/api/model-manager/download/${enc(jobId)}/cancel`, { method: 'POST' }),

  angleStatus: () => request<AngleStatus>('/api/film/multi-angle/status'),
}
