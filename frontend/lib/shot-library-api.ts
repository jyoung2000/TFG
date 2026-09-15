// Typed client for /api/shot-library.

import { backendFetch, getBackendCredentials } from './backend'
import { mediaResolver } from './media-resolver'
import type { FilmShot } from '../types/film'
import type { LibraryListing, LibraryShot, LibrarySort } from '../types/shot-library'

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

export interface LibraryQuery {
  q?: string
  tags?: string[]
  favorite?: boolean
  archived?: boolean
  model?: string
  sort?: LibrarySort
}

export const shotLibraryApi = {
  list: (query: LibraryQuery = {}) => {
    const params = new URLSearchParams()
    if (query.q) params.set('q', query.q)
    for (const tag of query.tags ?? []) params.append('tags', tag)
    if (query.favorite !== undefined) params.set('favorite', String(query.favorite))
    if (query.archived) params.set('archived', 'true')
    if (query.model) params.set('model', query.model)
    if (query.sort) params.set('sort', query.sort)
    const search = params.toString()
    return request<LibraryListing>(`/api/shot-library${search ? `?${search}` : ''}`)
  },

  get: (id: string) => request<LibraryShot>(`/api/shot-library/${enc(id)}`),

  save: (input: {
    project_id: string
    shot_id: string
    title?: string
    notes?: string
    tags?: string[]
    rating?: number
    version_number?: number | null
  }) => request<LibraryShot>('/api/shot-library', { method: 'POST', body: JSON.stringify(input) }),

  /** Only the fields sent are changed, so a rating edit cannot blank the notes. */
  update: (
    id: string,
    patch: { title?: string; notes?: string; tags?: string[]; rating?: number; favorite?: boolean },
  ) => request<LibraryShot>(`/api/shot-library/${enc(id)}`, { method: 'PUT', body: JSON.stringify(patch) }),

  duplicate: (id: string) =>
    request<LibraryShot>(`/api/shot-library/${enc(id)}/duplicate`, { method: 'POST' }),

  /** An empty shot_id adds a new shot to the scene instead of overwriting one. */
  apply: (id: string, target: { project_id: string; scene_id: string; shot_id?: string; overwrite_prompt?: boolean }) =>
    request<FilmShot>(`/api/shot-library/${enc(id)}/apply`, { method: 'POST', body: JSON.stringify(target) }),

  archive: (id: string) => request<LibraryShot>(`/api/shot-library/${enc(id)}/archive`, { method: 'POST' }),

  restore: (id: string) => request<LibraryShot>(`/api/shot-library/${enc(id)}/restore`, { method: 'POST' }),

  /** Permanent, and takes the copied preview with it. Archive is the reversible one. */
  remove: (id: string) =>
    request<{ status: string }>(`/api/shot-library/${enc(id)}`, { method: 'DELETE' }),
}

/**
 * The URL for an item's copied preview.
 *
 * Same shape as `filmOutputUrl`: the backend serves it by item id (the path
 * never comes from the caller), and the standalone build, which has no server,
 * resolves the stored path to a `data:`/`blob:` URL instead.
 */
export async function libraryPreviewUrl(item: LibraryShot): Promise<string> {
  const standalone = mediaResolver()
  if (standalone) return standalone.output(item.preview_path)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/shot-library/${enc(item.id)}/preview?token=${enc(token)}`
}
