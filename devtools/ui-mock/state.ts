/**
 * Mutable state for the UI-only mock backend.
 *
 * Mirrors what the Python backend owns: film projects, app settings (with the
 * write-only secrets kept out of every response), the generation queue and the
 * model-download jobs. Persisted to disk so a dev-server restart does not
 * throw away whatever you were looking at; `POST /api/__ui_mock/reset` puts it
 * back to the seed.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

import type { FilmProject, FilmQueue, QueuedJob } from '../../frontend/types/film'
import type { AppSettings, ClearableKeyProvider } from '../../frontend/types/settings'
import type { LibraryDownloadStatus } from '../../frontend/types/models'
import { DEMO_PROJECT_ID, emptyProject, seedProject, seedSettings } from './seed'

/** One simulated render, advanced by wall-clock time rather than a timer. */
export interface MockJob extends QueuedJob {
  /** Epoch ms when this job started running, or null while it is pending. */
  started_at: number | null
  duration_ms: number
}

export interface MockGeneration {
  id: string
  status: 'running' | 'complete' | 'failed' | 'cancelled'
  progress: number
  phase: string
  prompt: string
  output_path: string
  started_at: number
  duration_ms: number
}

export interface MockState {
  projects: Record<string, FilmProject>
  settings: AppSettings
  /** Stored secrets. Never serialized into a response — only `has*` flags are. */
  keys: Record<ClearableKeyProvider, string>
  queue: { active: MockJob | null; pending: MockJob[]; paused: boolean }
  libraryDownload: LibraryDownloadStatus
  /** Model ids the user typed into the library's custom-id row. */
  rememberedModels: { provider: string; model_id: string }[]
  /** Weight download state for the host's own models, keyed by model id. */
  modelDownloads: Record<string, { progress: number; downloaded: boolean }>
  generation: MockGeneration | null
  downloadedModels: string[]
}

export const EMPTY_LIBRARY_DOWNLOAD: LibraryDownloadStatus = {
  active: false,
  provider: '',
  model_id: '',
  status: 'idle',
  files_total: 0,
  files_done: 0,
  downloaded_bytes: 0,
  total_bytes: 0,
  progress: 0,
  error: '',
  message: '',
}

export function freshState(): MockState {
  const project = seedProject()
  return {
    projects: { [project.id]: project },
    settings: seedSettings(),
    keys: {
      ltx: '',
      fal: '',
      gemini: '',
      openrouter: '',
      'openai-compatible': '',
      anthropic: '',
      xai: '',
      wavespeed: '',
      replicate: '',
    },
    queue: { active: null, pending: [], paused: false },
    libraryDownload: { ...EMPTY_LIBRARY_DOWNLOAD },
    rememberedModels: [],
    modelDownloads: {},
    generation: null,
    downloadedModels: ['checkpoint', 'text_encoder'],
  }
}

export class Store {
  private state: MockState
  private saveTimer: NodeJS.Timeout | null = null

  constructor(private readonly file: string) {
    this.state = this.load()
  }

  get data(): MockState {
    return this.state
  }

  /** Read-modify-write helper that persists once the mutation returns. */
  mutate<T>(fn: (state: MockState) => T): T {
    const result = fn(this.state)
    this.scheduleSave()
    return result
  }

  reset(): void {
    this.state = freshState()
    this.scheduleSave()
  }

  project(id: string): FilmProject | null {
    return this.state.projects[id] ?? null
  }

  /**
   * The project the UI asked for. The renderer mints its own project ids on
   * "New film", so an unknown id creates one on demand rather than 404-ing —
   * empty, like a new film in the real app. Only the demo id carries a story.
   */
  ensureProject(id: string, name = ''): FilmProject {
    const existing = this.state.projects[id]
    if (existing) return existing
    const created = id === DEMO_PROJECT_ID ? seedProject(id, name) : emptyProject(id, name)
    this.mutate(state => {
      state.projects[id] = created
    })
    return created
  }

  private load(): MockState {
    try {
      const parsed = JSON.parse(readFileSync(this.file, 'utf8')) as MockState
      // A stored file from an older shape would break the UI in confusing
      // ways; a missing project map is the cheapest reliable signal.
      if (parsed && typeof parsed === 'object' && parsed.projects) return parsed
    } catch {
      // No state yet, or it is unreadable — seed instead.
    }
    return freshState()
  }

  private scheduleSave(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer)
    this.saveTimer = setTimeout(() => {
      try {
        mkdirSync(dirname(this.file), { recursive: true })
        writeFileSync(this.file, JSON.stringify(this.state, null, 2))
      } catch {
        // Persistence is a convenience; a read-only disk must not break the UI.
      }
    }, 250)
    this.saveTimer.unref?.()
  }
}

/** Queue snapshot in the shape `GET /api/film/queue` returns. */
export function queueSnapshot(state: MockState): FilmQueue {
  const active = state.queue.active
  return {
    active: active ? stripJob(active) : null,
    pending: state.queue.pending.map(stripJob),
    paused: state.queue.paused,
    progress: active ? jobProgress(active) : null,
    phase: active ? phaseFor(jobProgress(active)) : '',
  }
}

export function stripJob(job: MockJob): QueuedJob {
  const { project_id, scene_id, shot_id, shot_title, kind, version_number, status } = job
  return { project_id, scene_id, shot_id, shot_title, kind, version_number, status }
}

export function jobProgress(job: MockJob): number {
  if (job.started_at == null) return 0
  const elapsed = Date.now() - job.started_at
  return Math.min(99, Math.round((elapsed / job.duration_ms) * 100))
}

export function phaseFor(progress: number): string {
  if (progress < 10) return 'Preparing'
  if (progress < 25) return 'Encoding prompt'
  if (progress < 90) return 'Denoising'
  return 'Decoding frames'
}
