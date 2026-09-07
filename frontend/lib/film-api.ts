// Typed client for the backend /api/film surface.

import { backendFetch, getBackendCredentials } from './backend'
import type {
  CompositionScene,
  ContinuityWarning,
  DirectorCommandResult,
  FilmAsset,
  FilmAssetKind,
  FilmCapabilities,
  FilmPose,
  FilmProject,
  FilmProjectSettings,
  FilmQueue,
  FilmScene,
  FilmShot,
  QueuedJob,
  Vec3,
  VersionKind,
} from '../types/film'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await backendFetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.message === 'string' ? body.message : JSON.stringify(body)
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

const enc = encodeURIComponent

export const filmApi = {
  getProject: (projectId: string) =>
    request<{ project: FilmProject }>(`/api/film/projects/${enc(projectId)}`).then(r => r.project),

  updateScript: (projectId: string, content: string) =>
    request<{ project: FilmProject }>(`/api/film/projects/${enc(projectId)}/script`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }).then(r => r.project),

  updateSettings: (projectId: string, settings: FilmProjectSettings) =>
    request<{ project: FilmProject }>(`/api/film/projects/${enc(projectId)}/settings`, {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    }).then(r => r.project),

  createAsset: (projectId: string, data: { kind: FilmAssetKind; name: string } & Partial<FilmAsset>) =>
    request<{ asset: FilmAsset }>(`/api/film/projects/${enc(projectId)}/assets`, {
      method: 'POST',
      body: JSON.stringify(data),
    }).then(r => r.asset),

  updateAsset: (projectId: string, assetId: string, data: Partial<FilmAsset>) =>
    request<{ asset: FilmAsset }>(`/api/film/projects/${enc(projectId)}/assets/${enc(assetId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }).then(r => r.asset),

  deleteAsset: (projectId: string, assetId: string) =>
    request<{ status: string }>(`/api/film/projects/${enc(projectId)}/assets/${enc(assetId)}`, {
      method: 'DELETE',
    }),

  addAssetReference: (projectId: string, assetId: string, imageBase64: string, nameHint: string) =>
    request<{ asset: FilmAsset }>(
      `/api/film/projects/${enc(projectId)}/assets/${enc(assetId)}/references`,
      {
        method: 'POST',
        body: JSON.stringify({ image_base64: imageBase64, name_hint: nameHint }),
      },
    ).then(r => r.asset),

  createScene: (projectId: string, data: Partial<FilmScene>) =>
    request<FilmScene>(`/api/film/projects/${enc(projectId)}/scenes`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateScene: (projectId: string, sceneId: string, data: Partial<FilmScene> & { clear_location?: boolean }) =>
    request<FilmScene>(`/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteScene: (projectId: string, sceneId: string) =>
    request<{ status: string }>(`/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}`, {
      method: 'DELETE',
    }),

  reorderScenes: (projectId: string, orderedIds: string[]) =>
    request<{ project: FilmProject }>(`/api/film/projects/${enc(projectId)}/scenes/reorder`, {
      method: 'POST',
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }).then(r => r.project),

  createShot: (projectId: string, sceneId: string, data: Partial<FilmShot>) =>
    request<FilmShot>(`/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateShot: (
    projectId: string,
    sceneId: string,
    shotId: string,
    data: Partial<Omit<FilmShot, 'composition'>> & {
      composition?: CompositionScene | null
      clear_location?: boolean
    },
  ) =>
    request<FilmShot>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  deleteShot: (projectId: string, sceneId: string, shotId: string) =>
    request<{ status: string }>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}`,
      { method: 'DELETE' },
    ),

  reorderShots: (projectId: string, sceneId: string, orderedIds: string[]) =>
    request<FilmScene>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/reorder`,
      { method: 'POST', body: JSON.stringify({ ordered_ids: orderedIds }) },
    ),

  duplicateShot: (projectId: string, sceneId: string, shotId: string) =>
    request<FilmShot>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}/duplicate`,
      { method: 'POST' },
    ),

  captureShot: (
    projectId: string,
    sceneId: string,
    shotId: string,
    imageBase64: string,
    composition: CompositionScene,
  ) =>
    request<FilmShot>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}/capture`,
      { method: 'POST', body: JSON.stringify({ image_base64: imageBase64, composition }) },
    ),

  generateShot: (projectId: string, sceneId: string, shotId: string, kind: VersionKind) =>
    request<{ status: string; version_number: number; warnings: ContinuityWarning[] }>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}/generate`,
      { method: 'POST', body: JSON.stringify({ kind }) },
    ),

  generateBatch: (
    projectId: string,
    data: { kind: VersionKind; scene_id?: string; shot_ids?: string[] },
  ) =>
    request<{ status: string; queued: QueuedJob[] }>(
      `/api/film/projects/${enc(projectId)}/generate/batch`,
      { method: 'POST', body: JSON.stringify(data) },
    ),

  promoteVersion: (projectId: string, sceneId: string, shotId: string, number: number) =>
    request<{ status: string; current_version: number }>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}/versions/${number}/promote`,
      { method: 'POST' },
    ),

  savePose: (projectId: string, name: string, joints: Record<string, Vec3>, category = 'custom') =>
    request<{ pose: FilmPose }>(`/api/film/projects/${enc(projectId)}/poses`, {
      method: 'POST',
      body: JSON.stringify({ name, category, joints }),
    }).then(r => r.pose),

  deletePose: (projectId: string, poseId: string) =>
    request<{ status: string }>(`/api/film/projects/${enc(projectId)}/poses/${enc(poseId)}`, {
      method: 'DELETE',
    }),

  continuity: (projectId: string, shotId: string) =>
    request<{ warnings: ContinuityWarning[] }>(
      `/api/film/projects/${enc(projectId)}/continuity/${enc(shotId)}`,
    ).then(r => r.warnings),

  queue: () => request<FilmQueue>('/api/film/queue'),

  cancelQueue: () => request<FilmQueue>('/api/film/queue/cancel', { method: 'POST' }),

  capabilities: () => request<FilmCapabilities>('/api/film/capabilities'),

  directorCommand: (projectId: string, name: string, params: Record<string, unknown>) =>
    request<{ results: DirectorCommandResult[] }>(
      `/api/film/projects/${enc(projectId)}/director/command`,
      { method: 'POST', body: JSON.stringify({ name, params }) },
    ).then(r => r.results),

  directorInstruct: (projectId: string, instruction: string, sceneId?: string, shotId?: string) =>
    request<{ plan_summary: string; results: DirectorCommandResult[] }>(
      `/api/film/projects/${enc(projectId)}/director/instruct`,
      {
        method: 'POST',
        body: JSON.stringify({ instruction, scene_id: sceneId ?? null, shot_id: shotId ?? null }),
      },
    ),

  generateStoryboard: (
    projectId: string,
    data: { use_llm: boolean; target_shots_per_scene?: number; replace_existing?: boolean },
  ) =>
    request<{
      status: string
      scenes_created: number
      shots_created: number
      characters_created: number
      used_llm: boolean
    }>(`/api/film/projects/${enc(projectId)}/storyboard/generate`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

/** Authenticated URL for a film-project media file (capture, reference image). */
export async function filmMediaUrl(projectId: string, relativePath: string): Promise<string> {
  const { url, token } = await getBackendCredentials()
  return `${url}/api/film/projects/${enc(projectId)}/media?path=${enc(relativePath)}&token=${enc(token)}`
}

/** Authenticated URL for a generated output living in the outputs directory. */
export async function filmOutputUrl(outputPath: string): Promise<string> {
  const { url, token } = await getBackendCredentials()
  return `${url}/api/film/output?path=${enc(outputPath)}&token=${enc(token)}`
}
