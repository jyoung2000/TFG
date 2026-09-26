import { backendFetch } from './backend'
import type { CameraMove, CompositionScene, FilmProject } from '../types/film'
import type { ShotSpec, SpecLayout3D } from '../types/shotspec'
import type { VideoAnalysis } from '../types/video-analysis'

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

const enc = encodeURIComponent

export interface SceneBuildResult {
  layout3d: SpecLayout3D
  composition: CompositionScene
  camera_words: Record<string, string>
  camera_sentence: string
  reprojection_error: number
  svg: string
}

export interface CameraWords {
  camera_words: Record<string, string>
  camera_sentence: string
}

export const sceneApi = {
  build: (spec: ShotSpec, durationSeconds: number, cameraMove?: CameraMove) =>
    request<SceneBuildResult>('/api/scene/build', { method: 'POST', body: JSON.stringify({ spec, duration_seconds: durationSeconds, camera_move: cameraMove ?? null }) }),
  describe: (layout3d: SpecLayout3D) => request<CameraWords>('/api/scene/describe', { method: 'POST', body: JSON.stringify({ layout3d }) }),
  storyboard3d: (analysisId: string, options: { project_id?: string; name?: string } = {}) =>
    request<FilmProject>(`/api/video-analysis/${enc(analysisId)}/storyboard3d`, { method: 'POST', body: JSON.stringify(options) }),
  updateShotSpec: (analysisId: string, shotId: string, payload: { sections?: Partial<ShotSpec>; locks?: Record<string, boolean>; composition?: CompositionScene | null }) =>
    request<VideoAnalysis>(`/api/video-analysis/${enc(analysisId)}/shots/${enc(shotId)}/spec`, { method: 'PUT', body: JSON.stringify(payload) }),
}
