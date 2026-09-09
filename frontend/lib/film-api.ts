// Typed client for the backend /api/film surface.

import { backendFetch, getBackendCredentials } from './backend'
import { mediaResolver } from './media-resolver'
import type {
  CompositionScene,
  ContinuityReport,
  ContinuityWarning,
  DirectorChatMessage,
  DirectorChatResponse,
  DirectorCommandResult,
  DirectorContextDetails,
  DirectorInstructResponse,
  DirectorRole,
  DirectorStatus,
  FilmAsset,
  FilmBuildPlan,
  OpenRouterModelInfo,
  OpenRouterValidation,
  PackageSummary,
  ProjectContinuity,
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
  VisualReview,
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

  /** Whole-project replacement used by undo/redo (refused while a shot is queued/rendering). */
  replaceProject: (projectId: string, project: FilmProject) =>
    request<{ project: FilmProject }>(`/api/film/projects/${enc(projectId)}`, {
      method: 'PUT',
      body: JSON.stringify({ project }),
    }).then(r => r.project),

  updateSettings: (projectId: string, settings: FilmProjectSettings) =>
    request<{ project: FilmProject }>(`/api/film/projects/${enc(projectId)}/settings`, {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    }).then(r => r.project),

  importGeneration: (
    projectId: string,
    data: {
      prompt: string
      output_path: string
      negative_prompt?: string
      model?: string
      resolution?: string
      duration_seconds?: number
      fps?: number
      seed?: number | null
      aspect_ratio?: string
      camera_motion?: string
      mode?: string
      input_image_path?: string
      title?: string
      project_name?: string
    },
  ) =>
    request<{ project: FilmProject; scene_id: string; shot_id: string; version_number: number }>(
      `/api/film/projects/${enc(projectId)}/import-generation`,
      { method: 'POST', body: JSON.stringify(data) },
    ),

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

  updateScene: (
    projectId: string,
    sceneId: string,
    data: Partial<FilmScene> & { clear_location?: boolean; clear_gap?: boolean },
  ) =>
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
      clear_gap?: boolean
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
    request<ContinuityReport>(`/api/film/projects/${enc(projectId)}/continuity/${enc(shotId)}`),

  projectContinuity: (projectId: string) =>
    request<ProjectContinuity>(`/api/film/projects/${enc(projectId)}/continuity`),

  fixContinuity: (projectId: string, shotId: string, kind: string, subjectId = '') =>
    request<{ fixed: boolean; message: string; report: ContinuityReport; shot: FilmShot }>(
      `/api/film/projects/${enc(projectId)}/continuity/${enc(shotId)}/fix`,
      { method: 'POST', body: JSON.stringify({ kind, subject_id: subjectId }) },
    ),

  /** Optional multimodal continuity review (previous last frame vs this first frame). */
  visualReview: (projectId: string, shotId: string) =>
    request<VisualReview>(`/api/film/projects/${enc(projectId)}/continuity/${enc(shotId)}/visual-review`, {
      method: 'POST',
    }),

  queue: () => request<FilmQueue>('/api/film/queue'),

  cancelQueue: () => request<FilmQueue>('/api/film/queue/cancel', { method: 'POST' }),

  pauseQueue: () =>
    request<{ status: string; queue: FilmQueue }>('/api/film/queue/pause', { method: 'POST' }).then(r => r.queue),

  resumeQueue: () =>
    request<{ status: string; queue: FilmQueue }>('/api/film/queue/resume', { method: 'POST' }).then(r => r.queue),

  cancelJob: (shotId: string) =>
    request<{ status: string; queue: FilmQueue }>(`/api/film/queue/${enc(shotId)}/cancel`, { method: 'POST' }).then(r => r.queue),

  prioritizeJob: (shotId: string) =>
    request<{ status: string; queue: FilmQueue }>(`/api/film/queue/${enc(shotId)}/prioritize`, { method: 'POST' }).then(r => r.queue),

  capabilities: () => request<FilmCapabilities>('/api/film/capabilities'),

  exportPackage: (projectId: string, destinationPath: string, includeOutputs: boolean) =>
    request<PackageSummary>(`/api/film/projects/${enc(projectId)}/export`, {
      method: 'POST',
      body: JSON.stringify({ destination_path: destinationPath, include_outputs: includeOutputs }),
    }),

  inspectPackage: (packagePath: string) =>
    request<PackageSummary>(`/api/film/packages/inspect?package_path=${enc(packagePath)}`),

  importPackage: (projectId: string, packagePath: string, replace: boolean) =>
    request<{ summary: PackageSummary; project: FilmProject }>(`/api/film/projects/${enc(projectId)}/import`, {
      method: 'POST',
      body: JSON.stringify({ package_path: packagePath, replace }),
    }),

  removeModel: (modelType: string) =>
    request<{ name: string; downloaded: boolean }>(`/api/models/${enc(modelType)}`, { method: 'DELETE' }),

  directorCommand: (projectId: string, name: string, params: Record<string, unknown>) =>
    request<{ results: DirectorCommandResult[] }>(
      `/api/film/projects/${enc(projectId)}/director/command`,
      { method: 'POST', body: JSON.stringify({ name, params }) },
    ).then(r => r.results),

  directorInstruct: (
    projectId: string,
    instruction: string,
    sceneId?: string,
    shotId?: string,
    history: DirectorChatMessage[] = [],
  ) =>
    request<DirectorInstructResponse>(`/api/film/projects/${enc(projectId)}/director/instruct`, {
      method: 'POST',
      body: JSON.stringify({
        instruction,
        scene_id: sceneId ?? null,
        shot_id: shotId ?? null,
        history,
      }),
    }),

  directorStatus: () => request<DirectorStatus>('/api/film/director/status'),

  openrouterModels: (refresh = false) =>
    request<{ models: OpenRouterModelInfo[]; fetched_at_ms: number; cached: boolean }>(
      `/api/film/director/openrouter/models${refresh ? '?refresh=true' : ''}`,
    ),

  /** Chat models a text provider offers for the configured key/endpoint. */
  directorModels: (provider: string, refresh = false) =>
    request<{ models: OpenRouterModelInfo[]; fetched_at_ms: number; cached: boolean }>(
      `/api/film/director/models/${enc(provider)}${refresh ? '?refresh=true' : ''}`,
    ),

  /** Render a reference image for an asset with the project's image model. */
  generateAssetReference: (projectId: string, assetId: string, prompt = '') =>
    request<{ asset: FilmAsset; prompt: string; provider: string; model: string; reference_path: string }>(
      `/api/film/projects/${enc(projectId)}/assets/${enc(assetId)}/generate-reference`,
      { method: 'POST', body: JSON.stringify({ prompt }) },
    ),

  /** Model list from the configured OpenAI-compatible endpoint (LM Studio, vLLM, …). */
  openaiCompatibleModels: () =>
    request<{ models: OpenRouterModelInfo[]; fetched_at_ms: number; cached: boolean }>(
      '/api/film/director/openai-compatible/models',
    ),

  validateOpenrouterKey: () =>
    request<OpenRouterValidation>('/api/film/director/openrouter/validate', { method: 'POST' }),

  directorChat: (
    messages: DirectorChatMessage[],
    options: { role?: DirectorRole; model_hint?: string; duration_seconds?: number } = {},
  ) =>
    request<DirectorChatResponse>('/api/film/director/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, ...options }),
    }),

  refinePrompt: (projectId: string, sceneId: string, shotId: string, guidance = '') =>
    request<{ shot: FilmShot; previous_prompt: string; context: DirectorContextDetails }>(
      `/api/film/projects/${enc(projectId)}/scenes/${enc(sceneId)}/shots/${enc(shotId)}/refine-prompt`,
      { method: 'POST', body: JSON.stringify({ guidance }) },
    ),

  buildFilm: (
    projectId: string,
    data: { idea: string; target_scenes?: number; target_shots_per_scene?: number; use_llm: boolean; style?: string },
  ) =>
    request<{ plan: FilmBuildPlan; used_llm: boolean; context: DirectorContextDetails | null }>(
      `/api/film/projects/${enc(projectId)}/build`,
      { method: 'POST', body: JSON.stringify(data) },
    ),

  applyBuild: (projectId: string, plan: FilmBuildPlan, replaceExisting: boolean) =>
    request<{
      status: string
      scenes_created: number
      shots_created: number
      characters_created: number
      locations_created: number
      project: FilmProject
    }>(`/api/film/projects/${enc(projectId)}/build/apply`, {
      method: 'POST',
      body: JSON.stringify({ plan, replace_existing: replaceExisting }),
    }),

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
  const standalone = mediaResolver()
  if (standalone) return standalone.media(projectId, relativePath)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/film/projects/${enc(projectId)}/media?path=${enc(relativePath)}&token=${enc(token)}`
}

/** Authenticated URL for a generated output living in the outputs directory. */
export async function filmOutputUrl(outputPath: string): Promise<string> {
  const standalone = mediaResolver()
  if (standalone) return standalone.output(outputPath)
  const { url, token } = await getBackendCredentials()
  return `${url}/api/film/output?path=${enc(outputPath)}&token=${enc(token)}`
}
