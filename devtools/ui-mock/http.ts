/**
 * Minimal request plumbing for the UI-only mock backend.
 *
 * The mock is served as real HTTP by the Vite dev server rather than by
 * patching `fetch` in the renderer, so `<img src>`, `<video src>`, redirects
 * and status codes all behave exactly as they do against the Python backend.
 * Nothing here is reachable from a production build.
 */

import type { IncomingMessage, ServerResponse } from 'node:http'

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
 * A response the caller wants to shape itself (media bytes, redirects) rather
 * than have serialized as JSON.
 */
export class RawResponse {
  constructor(
    readonly status: number,
    readonly headers: Record<string, string>,
    readonly body: Buffer | string | null,
  ) {}
}

export function redirect(location: string): RawResponse {
  return new RawResponse(302, { location }, null)
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

export async function readJsonBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  if (req.method === 'GET' || req.method === 'HEAD') return {}
  const chunks: Buffer[] = []
  for await (const chunk of req) chunks.push(chunk as Buffer)
  if (chunks.length === 0) return {}
  try {
    const parsed: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    return parsed !== null && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

export function sendJson(res: ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload ?? null)
  res.statusCode = status
  res.setHeader('content-type', 'application/json')
  res.setHeader('cache-control', 'no-store')
  res.end(body)
}

export function sendRaw(res: ServerResponse, raw: RawResponse): void {
  res.statusCode = raw.status
  for (const [key, value] of Object.entries(raw.headers)) res.setHeader(key, value)
  res.end(raw.body ?? undefined)
}
