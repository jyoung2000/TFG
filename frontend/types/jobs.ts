/**
 * Mirror of `backend/services/job_store/job_models.py` — snake_case, no
 * mapping layer. The History tab reads only these.
 */

export type JobKind =
  | 'image_gen'
  | 'video_gen'
  | 'image_reproduce'
  | 'video_reproduce'
  | 'analysis'
  | 'scene_build'
  | 'training'
  | 'download'

export type JobStatus = 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'

export const JOB_KINDS: JobKind[] = [
  'image_gen',
  'video_gen',
  'image_reproduce',
  'video_reproduce',
  'analysis',
  'scene_build',
  'training',
  'download',
]

export const JOB_KIND_LABEL: Record<JobKind, string> = {
  image_gen: 'Image',
  video_gen: 'Video',
  image_reproduce: 'Image reproduce',
  video_reproduce: 'Video reproduce',
  analysis: 'Analysis',
  scene_build: '3D scene',
  training: 'Training',
  download: 'Download',
}

export const ACTIVE_STATUSES: JobStatus[] = ['queued', 'running']

export interface JobOutput {
  path: string
  kind: 'image' | 'video' | 'file'
  width: number
  height: number
  duration: number
  /** Absolute path of a small JPEG preview ("" when none). */
  thumb: string
}

export interface Job {
  id: string
  kind: JobKind
  status: JobStatus
  /** 0..100 */
  progress: number
  phase: string
  title: string
  created_at: number
  updated_at: number
  started_at: number | null
  finished_at: number | null
  model: string
  provider: string
  seed: number | null
  prompt: string
  negative_prompt: string
  spec: Record<string, unknown>
  params: Record<string, unknown>
  inputs: Record<string, unknown>
  outputs: JobOutput[]
  metrics: Record<string, unknown>
  parent_job_id: string
  project_id: string
  shot_id: string
  error: string
}

export interface JobListResponse {
  jobs: Job[]
  next_cursor: string
}

export interface JobDetailResponse {
  job: Job
  lineage: Job[]
  children: Job[]
}

export interface JobDeleteResponse {
  deleted: boolean
  removed_files: string[]
}

export interface LegacyQuickEntry {
  prompt: string
  negative_prompt?: string
  seed?: number | null
  video_path: string
  created_at?: number
  params?: Record<string, unknown>
}

export interface ImportJobsResponse {
  imported: number
  skipped: number
}

export function isActive(job: Job): boolean {
  return job.status === 'queued' || job.status === 'running'
}
