/**
 * Jobs API client plus the live change feed.
 *
 * The feed prefers server-sent events (`/api/jobs/events`, query-token
 * authenticated because EventSource cannot send headers). When the stream
 * fails — no backend, the mock server, a proxy that buffers — it falls back
 * to polling the list every two seconds, so History is never frozen.
 */

import { backendFetch, getBackendCredentials } from './backend'
import { logger } from './logger'
import { STANDALONE_UI } from './media-resolver'
import type {
  ImportJobsResponse,
  Job,
  JobDeleteResponse,
  JobDetailResponse,
  JobListResponse,
  LegacyQuickEntry,
} from '../types/jobs'

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

export interface JobListQuery {
  kind?: string
  /** A status, or `active` for queued + running. */
  status?: string
  project?: string
  q?: string
  limit?: number
  cursor?: string
}

export const jobsApi = {
  list: (query: JobListQuery = {}) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '' && value !== null) params.set(key, String(value))
    }
    const suffix = params.toString()
    return request<JobListResponse>(`/api/jobs${suffix ? `?${suffix}` : ''}`)
  },
  get: (id: string) => request<JobDetailResponse>(`/api/jobs/${enc(id)}`),
  remove: (id: string, files: boolean) =>
    request<JobDeleteResponse>(`/api/jobs/${enc(id)}?files=${files ? 'true' : 'false'}`, { method: 'DELETE' }),
  cancel: (id: string) => request<Job>(`/api/jobs/${enc(id)}/cancel`, { method: 'POST' }),
  rerun: (id: string) => request<Job>(`/api/jobs/${enc(id)}/rerun`, { method: 'POST' }),
  importLegacy: (entries: LegacyQuickEntry[]) =>
    request<ImportJobsResponse>('/api/jobs/import', { method: 'POST', body: JSON.stringify({ entries }) }),
}

export type JobFeedEvent = { type: 'job'; job: Job } | { type: 'deleted'; id: string } | { type: 'reset' }

export interface JobFeedHandle {
  close(): void
  /** How the feed is currently delivered; useful for the UI's status line. */
  mode(): 'sse' | 'poll' | 'connecting'
}

const POLL_INTERVAL_MS = 2000
const SSE_STARTUP_GRACE_MS = 4000
/** The mock backend cannot stream, so the UI-only modes poll from the start. */
const NO_STREAM = import.meta.env.VITE_UI_MOCK === '1' || STANDALONE_UI

/**
 * Subscribe to job changes. `onEvent` fires per changed job; on `reset` the
 * caller should refetch its list.
 */
export function subscribeJobs(onEvent: (event: JobFeedEvent) => void, onModeChange?: (mode: 'sse' | 'poll') => void): JobFeedHandle {
  let closed = false
  let mode: 'sse' | 'poll' | 'connecting' = 'connecting'
  let source: EventSource | null = null
  let pollTimer: number | null = null
  /** updated_at per job id as last delivered, so a poll only re-emits real changes. */
  const seen = new Map<string, number>()

  const startPolling = () => {
    if (closed || pollTimer !== null) return
    mode = 'poll'
    onModeChange?.('poll')
    const tick = async () => {
      if (closed) return
      try {
        const { jobs } = await jobsApi.list({ limit: 60 })
        for (const job of jobs) {
          if (seen.get(job.id) === job.updated_at) continue
          seen.set(job.id, job.updated_at)
          onEvent({ type: 'job', job })
        }
      } catch (err) {
        logger.warn(`Job poll failed: ${err instanceof Error ? err.message : String(err)}`)
      }
    }
    void tick()
    pollTimer = window.setInterval(() => void tick(), POLL_INTERVAL_MS)
  }

  const startSse = async () => {
    if (typeof EventSource === 'undefined') {
      startPolling()
      return
    }
    let url: string
    let token: string
    try {
      ;({ url, token } = await getBackendCredentials())
    } catch {
      startPolling()
      return
    }
    if (closed) return
    const endpoint = `${url}/api/jobs/events${token ? `?token=${enc(token)}` : ''}`
    let opened = false
    try {
      source = new EventSource(endpoint)
    } catch {
      startPolling()
      return
    }
    const grace = window.setTimeout(() => {
      if (!opened) {
        source?.close()
        source = null
        startPolling()
      }
    }, SSE_STARTUP_GRACE_MS)
    source.onopen = () => {
      opened = true
      window.clearTimeout(grace)
      mode = 'sse'
      onModeChange?.('sse')
    }
    source.addEventListener('job', event => {
      try {
        const job = JSON.parse((event as MessageEvent<string>).data) as Job
        seen.set(job.id, job.updated_at)
        onEvent({ type: 'job', job })
      } catch (err) {
        logger.warn(`Bad job event: ${err}`)
      }
    })
    source.addEventListener('deleted', event => {
      try {
        const { id } = JSON.parse((event as MessageEvent<string>).data) as { id: string }
        onEvent({ type: 'deleted', id })
      } catch {
        /* ignore */
      }
    })
    source.addEventListener('reset', () => onEvent({ type: 'reset' }))
    source.onerror = () => {
      // The browser retries on its own; only give up (and poll) when the
      // stream never opened — a 404 from the mock, a closed backend.
      if (!opened) {
        window.clearTimeout(grace)
        source?.close()
        source = null
        startPolling()
      }
    }
  }

  if (NO_STREAM) startPolling()
  else void startSse()

  return {
    close() {
      closed = true
      source?.close()
      source = null
      if (pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
    },
    mode: () => mode,
  }
}

const LEGACY_KEY = 'ltx-quick-history'
const LEGACY_DONE_KEY = 'ltx-quick-history-imported'

/**
 * One-time import of the pre-History Quick-mode list that lived in
 * localStorage. Runs once per browser profile; the key is removed afterwards.
 */
export async function importLegacyQuickHistory(): Promise<ImportJobsResponse | null> {
  let raw: string | null = null
  try {
    if (localStorage.getItem(LEGACY_DONE_KEY)) return null
    raw = localStorage.getItem(LEGACY_KEY)
  } catch {
    return null
  }
  if (!raw) {
    try { localStorage.setItem(LEGACY_DONE_KEY, '1') } catch { /* ignore */ }
    return null
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!Array.isArray(parsed)) return null
  const entries: LegacyQuickEntry[] = []
  for (const item of parsed as Array<Record<string, unknown>>) {
    if (!item || typeof item.videoPath !== 'string' || typeof item.prompt !== 'string') continue
    const settings = (item.settings ?? {}) as Record<string, unknown>
    entries.push({
      prompt: item.prompt,
      negative_prompt: typeof item.negativePrompt === 'string' ? item.negativePrompt : '',
      seed: typeof item.seed === 'number' ? item.seed : null,
      video_path: item.videoPath,
      created_at: typeof item.createdAt === 'number' ? item.createdAt : 0,
      params: {
        model: settings.model,
        resolution: settings.videoResolution,
        duration: settings.duration,
        fps: settings.fps,
        aspectRatio: settings.aspectRatio,
      },
    })
  }
  const result = await jobsApi.importLegacy(entries)
  try {
    localStorage.setItem(LEGACY_DONE_KEY, '1')
    localStorage.removeItem(LEGACY_KEY)
  } catch {
    /* ignore */
  }
  return result
}
