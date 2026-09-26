/**
 * Remote backend (phase 9): point the desktop at a TFG backend running
 * elsewhere — the compose stack on an Unraid box, a workstation, a rented
 * GPU. The renderer keeps talking to `getBackend()`; only where that URL
 * points changes. Nothing is spawned locally while a remote is in use, and
 * media is fetched through the authenticated `/api/film/output` route rather
 * than `file://`, which cannot reach another machine.
 */
import { readAppState, writeAppState } from './app-state'

export interface RemoteBackendConfig {
  url: string
  token: string
  enabled: boolean
}

export interface RemoteProbeResult {
  ok: boolean
  status?: string
  gpu?: string
  modelsLoaded?: boolean
  error?: string
}

function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

export function getRemoteBackend(): RemoteBackendConfig {
  const state = readAppState()
  const raw = state.remoteBackend as Partial<RemoteBackendConfig> | undefined
  return {
    url: normalizeUrl(typeof raw?.url === 'string' ? raw.url : ''),
    token: typeof raw?.token === 'string' ? raw.token : '',
    enabled: raw?.enabled === true,
  }
}

export function setRemoteBackend(config: RemoteBackendConfig): RemoteBackendConfig {
  const next: RemoteBackendConfig = { url: normalizeUrl(config.url), token: config.token ?? '', enabled: config.enabled === true && !!normalizeUrl(config.url) }
  const state = readAppState()
  writeAppState({ ...state, remoteBackend: next })
  return next
}

/** `GET /health` on the remote with its token; never throws. */
export async function probeRemoteBackend(url: string, token: string, timeoutMs = 4000): Promise<RemoteProbeResult> {
  const base = normalizeUrl(url)
  if (!/^https?:\/\//.test(base)) return { ok: false, error: 'The URL must start with http:// or https://' }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    const response = await fetch(`${base}/health`, { signal: controller.signal, headers })
    if (response.status === 401) return { ok: false, error: 'The backend rejected the token (401)' }
    if (!response.ok) return { ok: false, error: `Health check failed (${response.status})` }
    const body = (await response.json()) as { status?: string; models_loaded?: boolean; gpu_info?: { name?: string } }
    return { ok: body.status === 'ok', status: body.status, gpu: body.gpu_info?.name, modelsLoaded: body.models_loaded }
  } catch (error) {
    return { ok: false, error: error instanceof Error && error.name === 'AbortError' ? `No answer within ${timeoutMs / 1000} s` : String(error) }
  } finally {
    clearTimeout(timer)
  }
}
