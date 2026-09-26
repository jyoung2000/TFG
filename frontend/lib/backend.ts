let cached: { url: string; token: string; remote?: boolean } | null = null

export async function getBackendCredentials(): Promise<{ url: string; token: string }> {
  if (!cached) cached = await window.electronAPI.getBackend()
  return cached
}

/** True once the app learned it talks to a backend on another machine (phase 9). */
export function isRemoteBackend(): boolean {
  return cached?.remote === true
}

/** The credentials already loaded, for synchronous URL building; null before the first fetch. */
export function cachedBackendCredentials(): { url: string; token: string } | null {
  return cached
}

export function resetBackendCredentials(): void {
  cached = null
}

export async function backendFetch(path: string, init?: RequestInit): Promise<Response> {
  const { url, token } = await getBackendCredentials()
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return fetch(`${url}${path}`, { ...init, headers })
}

export async function backendWsUrl(path: string): Promise<string> {
  const { url, token } = await getBackendCredentials()
  const ws = url.replace('http://', 'ws://')
  const sep = path.includes('?') ? '&' : '?'
  return `${ws}${path}${sep}token=${token}`
}
