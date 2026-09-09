/**
 * Request plumbing for the UI-only mock backend.
 *
 * Deliberately free of any Node or DOM API: the same handlers run behind the
 * Vite dev server (`node-adapter.ts`) and inside a plain browser with no
 * server at all (`browser.ts`, used by the standalone HTML build).
 */

export interface MockRequest {
  method: string
  /** Path without the query string, e.g. `/api/film/queue`. */
  path: string
  query: URLSearchParams
  /** Route parameters captured from the pattern, already URL-decoded. */
  params: Record<string, string>
  /** Parsed JSON body, or `{}` for bodies that are absent or unparseable. */
  body: Record<string, unknown>
}

export type MockHandler = (req: MockRequest) => unknown | Promise<unknown>

interface Route {
  method: string
  segments: string[]
  handler: MockHandler
}

/** Thrown by a handler to produce the backend's `{detail}` error envelope. */
export class MockHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

/**
 * A response the caller wants to shape itself (media, redirects) rather than
 * have serialized as JSON.
 */
export class RawResponse {
  constructor(
    readonly status: number,
    readonly headers: Record<string, string>,
    readonly body: string | null,
  ) {}
}

export function redirect(location: string): RawResponse {
  return new RawResponse(302, { location }, null)
}

/** What a platform adapter turns into its own response type. */
export interface MockResult {
  status: number
  headers: Record<string, string>
  body: string
}

export class Router {
  private readonly routes: Route[] = []

  /** `add('GET', '/api/film/projects/:id', handler)` — `:name` captures one segment. */
  add(method: string, pattern: string, handler: MockHandler): this {
    this.routes.push({ method, segments: pattern.split('/').filter(Boolean), handler })
    return this
  }

  get(pattern: string, handler: MockHandler) {
    return this.add('GET', pattern, handler)
  }
  post(pattern: string, handler: MockHandler) {
    return this.add('POST', pattern, handler)
  }
  put(pattern: string, handler: MockHandler) {
    return this.add('PUT', pattern, handler)
  }
  delete(pattern: string, handler: MockHandler) {
    return this.add('DELETE', pattern, handler)
  }

  match(method: string, path: string): { handler: MockHandler; params: Record<string, string> } | null {
    const parts = path.split('/').filter(Boolean)
    for (const route of this.routes) {
      if (route.method !== method || route.segments.length !== parts.length) continue
      const params: Record<string, string> = {}
      let ok = true
      for (let i = 0; i < route.segments.length; i++) {
        const segment = route.segments[i]
        const value = parts[i]
        if (segment.startsWith(':')) {
          params[segment.slice(1)] = safeDecode(value)
        } else if (segment !== value) {
          ok = false
          break
        }
      }
      if (ok) return { handler: route.handler, params }
    }
    return null
  }
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export function parseJsonBody(raw: string): Record<string, unknown> {
  if (!raw) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    return parsed !== null && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}
